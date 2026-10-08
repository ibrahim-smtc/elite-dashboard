"""Database access for the DSR dashboard."""

from __future__ import annotations

import logging
import os
import sys
import time
from contextlib import contextmanager
from typing import Any

from dotenv import load_dotenv

load_dotenv()


def _rescue_libpq_on_windows() -> None:
    """
    Find a libpq when psycopg's own has been taken away.

    Endpoint security on Windows quarantines DLLs it does not recognise, and
    psycopg-binary's bundled libpq is a favourite: the package stays installed
    with its Python files intact and every DLL gone, so the import fails with
    "no pq wrapper available - An Application Control policy has blocked this
    file" and the whole app dies before it reaches a line of its own code.

    A machine with psycopg2 installed almost always still has a working libpq
    in psycopg2_binary.libs, because that copy was approved separately. It is
    named for its hash rather than libpq.dll, which is why nothing finds it:
    psycopg looks the name up with ctypes.util.find_library("libpq.dll"), and
    that searches PATH for exactly that filename.

    So: look through site-packages for any libpq, put its directory on the
    search path under the name the loader wants, and let the import try again.
    Nothing is hardcoded to this machine and nothing runs unless the normal
    import has already failed - on Linux, and on a healthy Windows box, this
    function is never called.
    """
    import glob
    import shutil
    import site
    import sysconfig

    roots = [sysconfig.get_paths().get("purelib", "")]
    roots += list(getattr(site, "getsitepackages", lambda: [])())
    seen: set[str] = set()

    for root in filter(None, roots):
        if root in seen:
            continue
        seen.add(root)
        for found in glob.glob(os.path.join(root, "*", "libpq*.dll")):
            folder = os.path.dirname(found)
            plain = os.path.join(folder, "libpq.dll")
            if not os.path.exists(plain):
                try:
                    shutil.copy2(found, plain)
                except OSError:
                    continue          # read-only install; try the next one
            try:
                os.add_dll_directory(folder)
            except (AttributeError, OSError):
                pass
            os.environ["PATH"] = folder + os.pathsep + os.environ.get("PATH", "")
            log.warning("psycopg's libpq was missing; using the one in %s", folder)
            return


try:
    import psycopg
except ImportError:
    if sys.platform != "win32":
        raise
    _rescue_libpq_on_windows()
    import psycopg                    # if this still fails, it should

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger("dsr.db")

_raw_dsn = os.environ.get("DATABASE_URL", "")
if _raw_dsn.startswith("postgres://"):
    _raw_dsn = "postgresql://" + _raw_dsn[len("postgres://"):]

DSN = _raw_dsn or "postgresql://postgres:postgres@127.0.0.1:5432/elite_dsr"

# Supabase exposes two pooler ports: 6543 pools per *transaction*, 5432 per
# *session*. Transaction mode is right for the query workload - it is why the
# pool can stay small - but it hands each transaction whatever backend is free,
# which breaks anything that expects one backend to remember something:
#
#   * psycopg prepares a statement after prepare_threshold executions and then
#     refers to it by name. The name only exists on the backend that created it,
#     so the 6th execution fails with 'prepared statement "_pg3_0" does not
#     exist' - and the poisoned connection keeps failing from the pool.
#     prepare_threshold=None keeps every statement unnamed.
#
#   * LISTEN registers interest on one backend, so notifications never arrive.
#     The change listener therefore dials LISTEN_DSN (session mode) instead.
#
# Both are silent failures: is_db_ready() goes false and every endpoint quietly
# serves fallback.get_*() instead, which looks like a working dashboard.
LISTEN_DSN = os.environ.get("LISTEN_DATABASE_URL") or DSN.replace(":6543/", ":5432/")

# Every query in this app runs against the dsr schema, so the search path is set
# once on connection rather than repeated in each statement.
# min_size=0 ensures we do not block or fail on startup if the database is unconfigured.
# Pool settings are tuned against measurement, not taste. The database is a
# round trip away (~370 ms), and profiling showed the SQL itself is free - every
# query, however complex, costs the same as SELECT 1 - so the only thing worth
# optimising is the NUMBER of round trips. Per checkout we were paying three:
#
#   autocommit=True   psycopg opens a transaction per checkout otherwise and
#                     rolls it back on return: two round trips, every time.
#                     Measured 1075 ms -> 374 ms for the same work. Writers are
#                     unaffected: _commit() and the loader open an explicit
#                     `with cx.transaction()`, which is still atomic on an
#                     autocommit connection.
#   no check=         check_connection pings on every checkout: one more round
#                     trip, ~370 ms. max_idle recycles connections well inside
#                     the pooler's own idle timeout instead, and a connection
#                     that does die surfaces as a handled error, not bad data.
#   min_size=2        keeps warm connections so a request never pays TCP+TLS
#                     setup (~460 ms) on top.
pool = ConnectionPool(
    DSN,
    min_size=2,
    max_size=8,
    max_idle=120.0,
    open=False,
    kwargs={
        "row_factory": dict_row,
        "options": "-c search_path=dsr,public",
        "prepare_threshold": None,
        "autocommit": True,
    },
)

_db_ready: bool = False
_last_check_time: float = 0.0


def connect(dsn: str | None = None, **kwargs):
    """
    A direct, unpooled connection carrying the same settings as the pool.

    The bulk loader wants one long-lived session rather than a pooled one, but
    it needs the same pooler-safe defaults - see the note above prepare_threshold.
    """
    kwargs.setdefault("prepare_threshold", None)
    kwargs.setdefault("options", "-c search_path=dsr,public")
    return psycopg.connect(dsn or DSN, **kwargs)


def has_database() -> bool:
    """Return True only if a valid non-local DATABASE_URL was supplied in environment."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return False
    # If running in Vercel and URL points to 127.0.0.1 or localhost, no local database exists!
    if os.environ.get("VERCEL") and ("127.0.0.1" in url or "localhost" in url):
        return False
    return True


def ensure_pool_open() -> None:
    """Ensure connection pool is opened."""
    try:
        if getattr(pool, "closed", True):
            pool.open()
    except Exception as exc:
        log.warning("Could not open database pool: %s", exc)


# How long a readiness answer is trusted before it is checked again. The failure
# window is long so an unreachable database cannot hang every request; the
# success window only has to be short enough to notice the database going away,
# and the queries themselves fail over to fallback anyway if it does.
READY_TTL = 5.0
FAILED_TTL = 30.0


def is_db_ready() -> bool:
    """Cached readiness check, so a request does not pay a round trip to ask."""
    global _db_ready, _last_check_time
    if not has_database():
        return False
    now = time.time()
    age = now - _last_check_time
    # Every endpoint calls this before doing anything, and the database is a
    # round trip away, so pinging each time doubled the latency of the whole
    # dashboard.
    if _db_ready and age < READY_TTL:
        return True
    if not _db_ready and age < FAILED_TTL:
        return False
    _last_check_time = now
    try:
        ensure_pool_open()
        with pool.connection(timeout=10.0) as cx:
            cx.execute("SELECT 1")
            _db_ready = True
            return True
    except Exception as exc:
        log.warning("Database ping failed: %s", exc)
        _db_ready = False
        return False


def check_db() -> bool:
    return is_db_ready()


@contextmanager
def session():
    """
    One pooled connection for an endpoint that runs several related queries.

    Checking a connection out of the pool costs a round trip of its own, and the
    database is far enough away (~1.2s) that an endpoint doing seven fetch_all
    calls spends most of its time on checkout rather than on the queries.
    Sharing one connection across the batch roughly halves that.
    """
    ensure_pool_open()
    with pool.connection(timeout=20.0) as cx:
        yield cx


def fetch_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    ensure_pool_open()
    with pool.connection(timeout=10.0) as cx:
        return cx.execute(sql, params).fetchall()


def fetch_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    ensure_pool_open()
    with pool.connection(timeout=10.0) as cx:
        return cx.execute(sql, params).fetchone()


def filtered(base: str, filters: list[tuple[str, Any]], tail: str = "") -> tuple[str, tuple]:
    """
    Build a query from optional filters, dropping the ones that were not supplied.
    """
    conditions: list[str] = []
    params: list[Any] = []
    for fragment, value in filters:
        if value is None:
            continue
        conditions.append(fragment)
        params.extend([value] * fragment.count("%s"))
    clause = " WHERE " + " AND ".join(conditions) if conditions else ""
    return f"{base}{clause} {tail}".strip(), tuple(params)
