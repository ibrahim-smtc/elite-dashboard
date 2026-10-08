"""
Run SQL against the DSR database and print it as a table.

The PostgreSQL binaries this project installs do not ship psql (the embedded
distribution carries only the server, initdb and pg_ctl), so this stands in for
ad-hoc queries.

    python tools/sql.py "select * from v_daily_kpi"
    python tools/sql.py -f db/views.sql
    python tools/sql.py \\tables
    python tools/sql.py \\views
    python tools/sql.py \\d booking
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import psycopg

DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/elite_dsr",
)

# psql-style shortcuts for the handful of things worth not retyping.
SHORTCUTS = {
    r"\tables": """
        SELECT table_name,
               (SELECT count(*) FROM information_schema.columns c
                 WHERE c.table_schema = t.table_schema
                   AND c.table_name = t.table_name) AS columns
        FROM information_schema.tables t
        WHERE t.table_schema = 'dsr' AND t.table_type = 'BASE TABLE'
        ORDER BY table_name""",
    r"\views": """
        SELECT table_name FROM information_schema.views
        WHERE table_schema = 'dsr' ORDER BY table_name""",
    r"\counts": """
        SELECT relname AS table_name, n_live_tup AS approx_rows
        FROM pg_stat_user_tables WHERE schemaname = 'dsr'
        ORDER BY n_live_tup DESC""",
}


def describe(name: str) -> tuple[str, tuple]:
    return ("""
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_schema = 'dsr' AND table_name = %s
        ORDER BY ordinal_position""", (name,))


def render(cursor) -> None:
    if cursor.description is None:
        print(cursor.statusmessage or "ok")
        return
    headers = [d.name for d in cursor.description]
    rows = [["" if v is None else str(v) for v in row] for row in cursor.fetchall()]
    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
              for i, h in enumerate(headers)]
    widths = [min(w, 48) for w in widths]

    def line(cells):
        return " | ".join(c[:w].ljust(w) for c, w in zip(cells, widths))

    print(line(headers))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        print(line(row))
    print(f"\n({len(rows)} row{'s' if len(rows) != 1 else ''})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sql", nargs="?", help="a statement, or a \\shortcut")
    ap.add_argument("-f", "--file", help="run a .sql file instead")
    ap.add_argument("--dsn", default=DSN)
    args = ap.parse_args()

    params: tuple = ()
    if args.file:
        statement = Path(args.file).read_text(encoding="utf-8")
    elif args.sql in SHORTCUTS:
        statement = SHORTCUTS[args.sql]
    elif args.sql and args.sql.startswith(r"\d "):
        statement, params = describe(args.sql[3:].strip())
    elif args.sql:
        statement = args.sql
    else:
        ap.print_help()
        sys.exit(1)

    # A .sql file is a script (many statements, DO blocks); autocommit lets it run
    # as one batch the way psql -f would.
    with psycopg.connect(args.dsn, autocommit=bool(args.file)) as cx:
        cx.execute("SET search_path = dsr, public")
        # Pass None, not (), when there is nothing to bind: with a sequence
        # psycopg parses the statement for placeholders, and a script containing
        # format('... %I ...') would be rejected as a bad placeholder.
        cursor = cx.execute(statement, params or None)
        render(cursor)
        if not args.file:
            cx.commit()


if __name__ == "__main__":
    main()
