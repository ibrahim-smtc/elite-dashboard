"""
Build the standalone DSR snapshot page.

    python tools/build_snapshot.py

Reads the current state of the database, bakes it into the template as a JSON
block and writes a single self-contained HTML file. Nothing in the output talks
to a server, so it can be published as an Artifact or e-mailed as a file and it
will still render.

Re-run after a fresh `python -m etl.load_dsr` to refresh the numbers.
"""

from __future__ import annotations

import datetime
import decimal
import json
import os
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from etl import pii  # noqa: E402  (needs ROOT on the path)

TEMPLATE = ROOT / "tools" / "snapshot_template.html"
OUTPUT = ROOT / "app" / "static" / "snapshot.html"
DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/elite_dsr",
)

# label -> (sql, single_row?)
QUERIES = {
    "kpi":        ("SELECT * FROM v_daily_kpi", True),
    "funnel":     ("SELECT * FROM v_sales_funnel", True),
    "targets":    ("SELECT leads_target, td_target, booking_target, retail_target "
                   "FROM v_consultant_scorecard WHERE row_kind = 'GRAND_TOTAL'", True),
    "board":      ("SELECT * FROM v_consultant_leaderboard", False),
    "teams":      ("SELECT consultant, total_leads, booking_target, booking_achieved, "
                   "retail_target, retail_achieved FROM v_consultant_scorecard "
                   "WHERE row_kind = 'TEAM_TOTAL'", False),
    "sources":    ("SELECT * FROM v_leads_sourcewise ORDER BY leads DESC", False),
    "models":     ("SELECT * FROM v_model_position ORDER BY total_stock DESC", False),
    "demand":     ("SELECT * FROM v_model_demand ORDER BY enquiries DESC", False),
    "ageing":     ("SELECT * FROM v_stock_ageing", False),
    "backorders": ("SELECT * FROM v_backorders ORDER BY days_waiting DESC NULLS LAST", False),
    "deadline":   ("SELECT chassis_number, model, variant, colour, stock_aging_days, "
                   "nadcon_retail_date FROM v_stock "
                   "WHERE stock_status = 'FREESTOCK' AND nadcon_retail_date < CURRENT_DATE "
                   "ORDER BY nadcon_retail_date", False),
    "nocrm":      ("SELECT customer_name, consultant, model, variant, booking_date "
                   "FROM v_bookings WHERE is_current_period AND crm_entry_done IS FALSE "
                   "ORDER BY booking_date", False),
    "attach":     ("SELECT * FROM v_attachment_rates", True),
    "dq":         ("SELECT * FROM v_data_quality "
                   "ORDER BY array_position(ARRAY['high','medium','low'], severity)", False),
    "meta":       ("SELECT source_file, file_modified, finished_at FROM etl_run "
                   "ORDER BY run_id DESC LIMIT 1", True),
    "period":     ("SELECT label, period_start, period_end FROM dim_period LIMIT 1", True),
    "commit":     ("SELECT * FROM v_booking_commitments", False),
    "avail":      ("SELECT * FROM v_stock_availability "
                   "ORDER BY free_units DESC, model, variant", False),
}


def jsonable(value):
    if isinstance(value, decimal.Decimal):
        return float(value)
    if isinstance(value, (datetime.date, datetime.datetime, datetime.time)):
        return value.isoformat()
    raise TypeError(f"cannot serialise {type(value)}")


def main() -> None:
    with psycopg.connect(DSN, row_factory=dict_row) as cx:
        cx.execute("SET search_path = dsr, public")
        data = {}
        for label, (sql, single) in QUERIES.items():
            cursor = cx.execute(sql)
            data[label] = cursor.fetchone() if single else cursor.fetchall()

    template = TEMPLATE.read_text(encoding="utf-8")
    # Escaping "<" keeps any value in the data from closing the script element.
    blob = json.dumps(data, separators=(",", ":"), default=jsonable).replace("<", "\\u003c")
    # PII POLICY (2026-10-08): this page is made to be e-mailed and published,
    # so it must never carry a customer's phone or email - the back-order list
    # it bakes in used to include a mobile number. The database is redacted at
    # source (etl/pii.py, db/pii.sql), but a snapshot built from a database
    # that predates that would still carry them, so the finished data is
    # scrubbed here as well.
    blob = pii.scrub_text(blob)
    if "/*__DATA__*/" not in template:
        raise SystemExit(f"{TEMPLATE.name} has no /*__DATA__*/ placeholder")

    OUTPUT.write_text(template.replace("/*__DATA__*/", blob), encoding="utf-8")
    rows = sum(len(v) for v in data.values() if isinstance(v, list))
    print(f"wrote {OUTPUT.relative_to(ROOT)}  "
          f"{OUTPUT.stat().st_size / 1024:.0f} KB  ({rows} rows baked in)")


if __name__ == "__main__":
    main()
