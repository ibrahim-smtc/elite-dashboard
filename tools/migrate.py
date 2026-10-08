"""
Apply SQL files to the live database safely: all or nothing, dry run first.

    python tools/migrate.py db/triggers.sql db/pii.sql db/views.sql
    python tools/migrate.py db/triggers.sql db/pii.sql db/views.sql --commit
    python tools/migrate.py db/pii_backfill.sql            # dry run
    python tools/migrate.py db/pii_backfill.sql --commit

Added 2026-10-08. Applying db/views.sql by hand was risky: it drops and rebuilds
every view the dashboard reads, so a failure half way through leaves the
dashboard broken, and a change in what a view counts only shows up once it is
live. This runs every file inside ONE transaction and, before deciding anything,
reports:

  * the dashboard's headline figures before and after (enquiries, bookings,
    retails, stock...), so an unintended change is seen before it is live;
  * how many customer phone numbers, emails and addresses are still stored
    in the clear, before and after (the PII policy - see etl/pii.py);
  * workbook rows with no load_period_id, which the per-month views cannot
    place in a month.

Without --commit it then ROLLS BACK - nothing is changed, and nothing reaches
the open dashboards (notifications are only delivered on commit). With
--commit it commits, unless a headline figure moved, in which case it refuses
until --allow-figure-changes says the change is expected. If anything fails,
the whole run is rolled back and the database is exactly as it was.

It refuses to run a file containing DROP SCHEMA: db/schema.sql rebuilds the
database from nothing and must never be pointed at the live one.

The connection string comes from --dsn or DATABASE_URL (.env is read).
"""

from __future__ import annotations

import argparse
import os
import sys
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from etl import pii  # noqa: E402

# Every place customer PII can be stored: (schema, table, column, kind).
# "redact" columns hold only a phone/email/address; "scrub" columns are free
# text that may contain one. Mirrors the triggers in db/pii.sql.
PII_COLUMNS = [
    ("dsr", "lead", "mobile", "redact"), ("dsr", "lead", "email", "redact"),
    ("dsr", "lead", "enquiry_note", "scrub"),
    ("dsr", "booking", "mobile", "redact"), ("dsr", "booking", "notes", "scrub"),
    ("dsr", "test_drive", "mobile", "redact"), ("dsr", "test_drive", "email", "redact"),
    ("dsr", "registration", "contact_no", "redact"),
    ("dsr", "registration", "email", "redact"),
    ("dsr", "registration", "address", "redact"),
    ("dsr", "allotment", "remarks", "scrub"),
    ("public", "enquiries", "mobile", "redact"), ("public", "enquiries", "email", "redact"),
    ("public", "enquiries", "subject", "scrub"), ("public", "enquiries", "message", "scrub"),
    # Name fields can carry a phone or email the CRM export put there.
    ("dsr", "lead", "lead_name", "scrub"), ("dsr", "test_drive", "lead_name", "scrub"),
    ("dsr", "booking", "customer_name", "scrub"), ("dsr", "allotment", "customer_name", "scrub"),
    ("dsr", "registration", "customer_name", "scrub"),
    ("dsr", "registration", "nadcon_punched_customer", "scrub"),
    ("public", "enquiries", "full_name", "scrub"),
    # The test-drive board (db/test_drives.sql).
    ("dsr", "test_drive_booking", "phone", "redact"),
    ("dsr", "test_drive_booking", "address", "redact"),
    ("dsr", "test_drive_booking", "customer", "scrub"),
    ("dsr", "test_drive_booking", "note", "scrub"),
]

FACTS = ["lead", "booking", "test_drive", "allotment", "registration"]


def _num(v):
    if isinstance(v, Decimal):
        return float(v)
    return v


def _exists(cx, schema: str, table: str, column: str | None = None) -> bool:
    if column is None:
        return cx.execute("SELECT to_regclass(%s) IS NOT NULL",
                          (f"{schema}.{table}",)).fetchone()[0]
    return cx.execute(
        "SELECT EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = %s AND table_name = %s AND column_name = %s)",
        (schema, table, column)).fetchone()[0]


def figures(cx) -> dict:
    """The numbers the top of the dashboard shows, for the active month."""
    out: dict = {}
    if _exists(cx, "dsr", "v_daily_kpi"):
        row = cx.execute("SELECT row_to_json(k) FROM dsr.v_daily_kpi k").fetchone()
        for k, v in ((row[0] if row else None) or {}).items():
            if k != "period":
                out[f"kpi.{k}"] = _num(v)
        out["period"] = (row[0] or {}).get("period") if row else None
    if _exists(cx, "dsr", "v_attachment_rates"):
        out["attachments.registrations"] = _num(cx.execute(
            "SELECT registrations FROM dsr.v_attachment_rates").fetchone()[0])
    if _exists(cx, "dsr", "v_consultant_scorecard"):
        b, r = cx.execute(
            "SELECT sum(booking_achieved), sum(retail_achieved) "
            "FROM dsr.v_consultant_scorecard WHERE row_kind = 'CONSULTANT'").fetchone()
        out["scorecard.bookings"], out["scorecard.retails"] = _num(b), _num(r)
    return out


def pii_census(cx) -> dict:
    """How many stored values are still a customer's phone, email or address."""
    out = {}
    for schema, table, column, kind in PII_COLUMNS:
        if not _exists(cx, schema, table, column):
            continue
        if kind == "redact":
            sql = (f'SELECT count(*) FROM {schema}."{table}" '
                   f'WHERE "{column}" IS NOT NULL AND "{column}" <> %s')
            params = (pii.REDACTED,)
        else:
            sql = (f'SELECT count(*) FROM {schema}."{table}" '
                   f'WHERE "{column}" ~ %s OR "{column}" ~ %s OR "{column}" ~ %s')
            params = (pii.EMAIL_PATTERN, pii.MOBILE_PATTERN, pii.LANDLINE_PATTERN)
        out[f"{schema}.{table}.{column}"] = cx.execute(sql, params).fetchone()[0]
    return out


def unplaced_rows(cx) -> dict:
    """Workbook rows with no load_period_id - the per-month views cannot place them."""
    out = {}
    for t in FACTS:
        if _exists(cx, "dsr", t, "load_period_id"):
            out[t] = cx.execute(
                f"SELECT count(*) FROM dsr.{t} "
                f"WHERE origin = 'WORKBOOK' AND load_period_id IS NULL").fetchone()[0]
    return out


def _changed(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) > 1e-9
    return a != b


def main() -> int:
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", help="SQL files, applied in this order")
    ap.add_argument("--commit", action="store_true",
                    help="keep the changes (default: dry run, rolled back)")
    ap.add_argument("--allow-figure-changes", action="store_true",
                    help="commit even if a dashboard headline figure changes")
    ap.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    args = ap.parse_args()

    if not args.dsn:
        print("No database: set DATABASE_URL (or .env) or pass --dsn.")
        return 1

    scripts = []
    for f in args.files:
        path = Path(f)
        if not path.is_absolute():
            path = (Path.cwd() / path) if path.exists() else (ROOT / path)
        text = path.read_text(encoding="utf-8")
        if "DROP SCHEMA" in text.upper():
            print(f"Refusing {path.name}: it contains DROP SCHEMA and would wipe the "
                  f"database. It is for building a new one, not for migrating.")
            return 1
        scripts.append((path, text))

    # A transaction has to stay on one backend from start to finish, which the
    # Supabase transaction pooler (6543) guarantees but cannot keep the SET
    # statements these files make; the session pooler (5432) does both.
    dsn = args.dsn.replace("postgres://", "postgresql://", 1).replace(":6543/", ":5432/")
    print(f"database  {dsn.split('@')[-1]}")
    print(f"mode      {'COMMIT' if args.commit else 'DRY RUN (rolled back at the end)'}\n")

    with psycopg.connect(dsn, autocommit=False, prepare_threshold=None,
                         options="-c search_path=dsr,public") as cx:
        try:
            cx.execute("SET LOCAL statement_timeout = '10min'")
            # Rebuilding views waits for the dashboard's own queries to finish;
            # it should not wait forever behind a stuck one.
            cx.execute("SET LOCAL lock_timeout = '20s'")

            fig0, pii0, unplaced0 = figures(cx), pii_census(cx), unplaced_rows(cx)
            for path, text in scripts:
                cx.execute(text)
                print(f"applied   {path.relative_to(ROOT) if ROOT in path.parents else path}")
            fig1, pii1 = figures(cx), pii_census(cx)
        except Exception as exc:
            cx.rollback()
            print(f"\nFAILED - rolled back, nothing was changed.\n{type(exc).__name__}: {exc}")
            return 1

        print("\nDashboard headline figures (active month)")
        changed = []
        for k in sorted(set(fig0) | set(fig1)):
            a, b = fig0.get(k), fig1.get(k)
            mark = "  CHANGED" if _changed(a, b) else ""
            if mark:
                changed.append(k)
            print(f"  {k:<40} {str(a):>14} -> {str(b):<14}{mark}")

        print("\nCustomer PII still stored in the clear (should end at 0)")
        for k in sorted(pii0.keys() | pii1.keys()):
            print(f"  {k:<40} {pii0.get(k, '-'):>14} -> {pii1.get(k, '-')}")
        remaining = sum(v for v in pii1.values() if isinstance(v, int))

        if any(unplaced0.values()):
            print("\nWorkbook rows with no load_period_id (the per-month views cannot place these)")
            for t, n in unplaced0.items():
                if n:
                    print(f"  {t:<40} {n:>14}")

        if not args.commit:
            cx.rollback()
            print("\nDRY RUN - rolled back. Nothing was changed. "
                  "Re-run with --commit to apply.")
            return 0

        if changed and not args.allow_figure_changes:
            cx.rollback()
            print(f"\nNOT COMMITTED - {len(changed)} headline figure(s) changed: "
                  f"{', '.join(changed)}.\nIf that is expected, re-run with "
                  f"--commit --allow-figure-changes.")
            return 2

        cx.commit()
        print("\nCOMMITTED." + (f" {remaining} PII value(s) still stored in the clear."
                                if remaining else ""))
        return 0


if __name__ == "__main__":
    sys.exit(main())
