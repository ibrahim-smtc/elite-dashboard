"""
Who may sign in to the dashboard, and as what (ROLE-BASED ACCESS, 2026-10-13).

The account itself - email and password - is created in Supabase
(Authentication > Users > Add user, with "Auto Confirm User" ticked). This
tool sets what it may do. An account not listed here cannot use the dashboard.

    python tools/dashboard_users.py list
    python tools/dashboard_users.py add manager@example.com manager
    python tools/dashboard_users.py add sales1@example.com employee
    python tools/dashboard_users.py remove sales1@example.com

  manager    can reveal a customer's full phone number and email (logged)
  employee   sees phone numbers and emails masked only

--dsn URL  the database (default: DATABASE_URL from .env). A change takes
           effect within a minute (the server caches roles that long).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _dsn(arg: str | None) -> str:
    if not arg:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
        arg = os.environ.get("DATABASE_URL", "")
    if not arg:
        sys.exit("No database: set DATABASE_URL (or .env) or pass --dsn.")
    return arg.replace("postgres://", "postgresql://", 1).replace(":6543/", ":5432/")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["list", "add", "remove"])
    ap.add_argument("email", nargs="?")
    ap.add_argument("role", nargs="?", choices=["manager", "employee"])
    ap.add_argument("--dsn")
    args = ap.parse_args()

    import psycopg
    with psycopg.connect(_dsn(args.dsn), prepare_threshold=None) as cx:
        if args.command == "add":
            if not (args.email and args.role):
                ap.error("add needs an email and a role, e.g. add manager@example.com manager")
            cx.execute("""INSERT INTO dsr.dashboard_user (email, role) VALUES (lower(btrim(%s)), %s)
                          ON CONFLICT (email) DO UPDATE SET role = EXCLUDED.role""",
                       (args.email, args.role))
            print(f"{args.email.strip().lower()} can sign in as {args.role}.")
        elif args.command == "remove":
            if not args.email:
                ap.error("remove needs an email")
            n = cx.execute("DELETE FROM dsr.dashboard_user WHERE email = lower(btrim(%s))",
                           (args.email,)).rowcount
            print(f"{args.email.strip().lower()} removed." if n else "No such account on the list.")
        rows = cx.execute("SELECT email, role, added_at FROM dsr.dashboard_user "
                          "ORDER BY role, email").fetchall()
    print("\nAllowed to sign in:" if rows else "\nNobody is allowed to sign in yet.")
    for email, role, added in rows:
        print(f"  {role:<9} {email}   (added {added:%Y-%m-%d})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
