"""
One-step Cloud Database Initializer for Volkswagen Elite Motors DSR Dashboard.

Usage:
    python tools/setup_cloud_db.py "postgresql://user:password@ep-xyz.neon.tech/neondb?sslmode=require"
or:
    set DATABASE_URL=postgresql://user:password@ep-xyz.neon.tech/neondb?sslmode=require
    python tools/setup_cloud_db.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    if len(sys.argv) > 1:
        dsn = sys.argv[1].strip()
    else:
        dsn = os.environ.get("DATABASE_URL", "").strip()

    if not dsn:
        print("Error: Please provide a valid PostgreSQL connection string.")
        print('Example: python tools/setup_cloud_db.py "postgresql://postgres:postgres@127.0.0.1:5432/elite_dsr"')
        sys.exit(1)

    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]

    print(f"Connecting to database: {dsn.split('@')[-1]}...")
    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                ver = cur.fetchone()[0]
                print(f"Connected successfully: {ver[:40]}...")

                print("1/4 Applying db/schema.sql (18 tables & dimensions)...")
                schema_sql = (ROOT / "db" / "schema.sql").read_text(encoding="utf-8")
                cur.execute(schema_sql)

                print("2/4 Applying db/triggers.sql (real-time notification triggers)...")
                triggers_sql = (ROOT / "db" / "triggers.sql").read_text(encoding="utf-8")
                cur.execute(triggers_sql)

                print("   Applying db/test_drives.sql (test drives, filed from enquiries)...")
                cur.execute((ROOT / "db" / "test_drives.sql").read_text(encoding="utf-8"))

                # PII POLICY (2026-10-08): the redaction triggers go on before
                # the first load, so a new database never holds a customer's
                # phone, email or address even for a moment. AFTER test_drives.sql
                # on purpose: pii.sql guards that file's test_drive_booking table
                # and skips any table that does not exist yet.
                print("   Applying db/pii.sql (customer PII redaction triggers)...")
                cur.execute((ROOT / "db" / "pii.sql").read_text(encoding="utf-8"))

        os.environ["DATABASE_URL"] = dsn

        print("3/4 Running ETL to load DSR August 2026 workbook into PostgreSQL...")
        orig_argv = sys.argv[:]
        sys.argv = [sys.argv[0], "--dsn", dsn]
        from etl.load_dsr import main as run_etl
        try:
            run_etl()
        finally:
            sys.argv = orig_argv

        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                print("4/4 Applying db/views.sql (21 analytical views)...")
                views_sql = (ROOT / "db" / "views.sql").read_text(encoding="utf-8")
                cur.execute(views_sql)

                # Grant permissions to Supabase roles if present
                #
                # FIX (2026-10-08): this granted ALL on every dsr table to
                # `anon` and `authenticated` as well as service_role. On
                # Supabase, `anon` is the role behind the public anon key -
                # the one that ships inside website bundles (see the note on
                # public.enquiries in db/triggers.sql) - so anyone holding it
                # could read and rewrite the whole DSR database through
                # PostgREST. The app and the agents connect with the database
                # URL or the service key, which is service_role, so that is
                # the only role granted now.
                #
                # This only affects databases built with this script from now
                # on. An existing database keeps whatever it was granted; to
                # take it back there:
                #   REVOKE ALL ON ALL TABLES IN SCHEMA dsr FROM anon, authenticated;
                try:
                    cur.execute("""
                        DO $$
                        BEGIN
                            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
                                GRANT USAGE ON SCHEMA dsr TO service_role;
                                GRANT ALL ON ALL TABLES IN SCHEMA dsr TO service_role;
                                GRANT ALL ON ALL SEQUENCES IN SCHEMA dsr TO service_role;
                                GRANT ALL ON ALL ROUTINES IN SCHEMA dsr TO service_role;
                                ALTER DEFAULT PRIVILEGES IN SCHEMA dsr GRANT ALL ON TABLES TO service_role;
                            END IF;
                        END
                        $$;
                    """)
                except Exception:
                    pass

                cur.execute("SELECT count(*) FROM dsr.vehicle;")
                count = cur.fetchone()[0]

                # Update local .env file
                env_path = ROOT / ".env"
                env_path.write_text(f"DATABASE_URL={dsn}\n", encoding="utf-8")
                print(f"\nUpdated .env with cloud DATABASE_URL.")
                print(f"All set! Supabase database initialized with {count} vehicles.")
                print("\nNext step: Add this DATABASE_URL to your Vercel Project Settings:")
                print("  Vercel Dashboard -> Project -> Settings -> Environment Variables")
                print("  Key: DATABASE_URL")
                print(f"  Value: {dsn}")

    except Exception as exc:
        print(f"Error initializing database: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
