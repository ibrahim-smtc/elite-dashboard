"""
Volkswagen Elite Motors - Automated DSR Ingestion Pipeline Tool

Used by reporting agents and automated jobs to inject DSR Excel workbooks
into the CRM dashboard and PostgreSQL database.

Usage:
    python tools/inject_dsr.py "DSR August 2026.xlsx"
    python tools/inject_dsr.py "DSR August 2026.xlsx" --url https://your-crm.vercel.app --agent "Auto-Bot"
    python tools/inject_dsr.py "DSR August 2026.xlsx" --direct
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="Inject DSR Excel workbook into the CRM Dashboard.")
    parser.add_argument("file", help="Path to .xlsx or .xlsm file to inject")
    parser.add_argument(
        "--url",
        default=os.environ.get("CRM_URL", "http://127.0.0.1:8000"),
        help="Base URL of CRM Dashboard (default: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--agent",
        default="Reporting Agent",
        help="Name of reporting agent or manager injecting the file",
    )
    parser.add_argument(
        "--period",
        default=None,
        help="Optional period code (e.g. AUG2026, SEP2026)",
    )
    parser.add_argument(
        "--direct",
        action="store_true",
        help="Force direct database ETL injection instead of HTTP endpoint",
    )

    args = parser.parse_args()
    file_path = Path(args.file)
    if not file_path.exists():
        file_path = ROOT / args.file
    if not file_path.exists():
        print(f"Error: File not found: {args.file}")
        sys.exit(1)

    print(f"==================================================")
    print(f" DSR Workbook Ingestion Pipeline")
    print(f" File:   {file_path.name} ({file_path.stat().st_size:,} bytes)")
    print(f" Agent:  {args.agent}")
    print(f"==================================================")

    # FIX (2026-10-08): this posted to /api/upload-dsr, the synchronous route,
    # which always failed with 500 ("name 'mode' is not defined"), so every run
    # quietly fell through to the direct database load below. With that route
    # fixed, a workbook takes ~100 s there and this waited only 90 s - after
    # which it would ALSO have run the direct load, replacing the same month
    # twice at once. It now uses the background job the dashboard uses
    # (/api/upload-report/start, then poll the status), which answers at once.
    #
    # It falls back to the direct load only when the job could not be started
    # because the server is unreachable or too old to have that route. Once a
    # job is running it never falls back: the server is loading the month, and
    # losing contact does not mean the load stopped.
    if not args.direct:
        base = args.url.rstrip("/")
        start_endpoint = f"{base}/api/upload-report/start"
        print(f"Connecting to dashboard API: {start_endpoint}...")
        started = None
        try:
            with open(file_path, "rb") as f:
                data = {"uploaded_by": args.agent, "mode": "replace"}
                if args.period:
                    data["period"] = args.period
                files = {
                    "file": (
                        file_path.name,
                        f,
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    )
                }
                res = requests.post(start_endpoint, data=data, files=files,
                                    timeout=120)
            if res.status_code == 202:
                started = res.json()
            elif res.status_code == 404 or res.status_code >= 500:
                print(f"API returned status {res.status_code}: {res.text}")
                print("Falling back to direct database injection...")
            else:
                # The server looked at the file and refused it (a bad period,
                # say). The direct load would refuse the same file for the same
                # reason, or bypass a check that was refused on purpose.
                print(f"API refused the file ({res.status_code}): {res.text}")
                sys.exit(1)
        except requests.exceptions.RequestException as req_err:
            print(f"Could not connect to {args.url}: {req_err}")
            print("Falling back to direct database injection...")

        if started:
            job_id = started["job_id"]
            print(f"Ingest started for {started.get('period')} (job {job_id}). Waiting...")
            deadline = time.time() + 15 * 60
            while time.time() < deadline:
                time.sleep(3)
                try:
                    job = requests.get(f"{base}/api/upload-report/status/{job_id}",
                                       timeout=30).json()
                except (requests.exceptions.RequestException, ValueError):
                    continue
                print(f"  {job.get('step') or job.get('state')}...")
                if job.get("state") == "done":
                    body = job.get("result") or {}
                    print("\nInjection Successful!")
                    print(f"Status:      {body.get('status')}")
                    print(f"Message:     {body.get('message')}")
                    print(f"Period:      {body.get('period')} ({body.get('period_range')})")
                    print(f"Environment: {body.get('environment')}")
                    print("\nRecords Ingested:")
                    for k, v in (body.get("counts") or {}).items():
                        print(f"  - {k:<25}: {v:>6}")
                    return
                if job.get("state") == "failed":
                    print(f"\nIngest failed on the server: {job.get('error')}")
                    sys.exit(1)
            print("\nStill running after 15 minutes. Check the dashboard before retrying.")
            sys.exit(1)

    # Direct database injection fallback
    print("\nRunning direct database ETL ingestion...")
    dsn = os.environ.get("DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:5432/elite_dsr")
    if dsn.startswith("postgres://"):
        dsn = "postgresql://" + dsn[len("postgres://"):]

    try:
        import openpyxl
        import psycopg
        from etl.load_dsr import Loader
        from app.entry import _resolve_period

        period_label, start_d, end_d = _resolve_period(args.period, file_path.name)
        with open(file_path, "rb") as f:
            wb = openpyxl.load_workbook(f, data_only=True)

        with psycopg.connect(dsn, autocommit=True) as cx:
            # FIX (2026-10-08): one transaction around the load, as the API's
            # upload routes now use, so a replace that fails part-way does not
            # leave the month's rows deleted with nothing loaded in their place.
            with cx.transaction():
                loader = Loader(cx, wb, period_label, start_d, end_d)
                counts = loader.run()
                cx.execute(
                    """
                    INSERT INTO etl_run (source_file, file_modified, finished_at, row_counts, notes)
                    VALUES (%s, now(), now(), %s, %s)
                """,
                    (file_path.name, json.dumps(counts), f"Direct CLI by {args.agent}"),
                )

        print("\nDirect Ingestion Successful!")
        print(f"Period: {period_label} ({start_d} to {end_d})")
        print("\nRecords Ingested:")
        for k, v in counts.items():
            print(f"  - {k:<25}: {v:>6}")

    except Exception as exc:
        print(f"Direct ingestion failed: {exc}")
        sys.exit(1)


if __name__ == "__main__":
    main()
