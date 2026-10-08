"""
Text and CSV report ingestion parser for Volkswagen Elite Motors CRM.

Supports:
- CSV (.csv), TSV (.tsv), and Text (.txt) reports
- Automatic encoding detection (UTF-8, UTF-8-BOM, Latin-1, CP1252)
- Delimiter detection (comma, tab, semicolon, pipe)
- Multi-section DSR text reports (converted into in-memory openpyxl workbook)
- Single-table auto-detection: Bookings, Leads, Vehicles/Stock, Test Drives
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Any

import openpyxl
import psycopg

from app.db import DSN, connect as db_connect
from etl import dimensions as dims
from etl import normalize as nz
from etl import pii
from etl.load_dsr import Loader


def decode_bytes(content: bytes) -> str:
    """Safely decode raw bytes across common text encodings."""
    for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
        try:
            return content.decode(enc)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def detect_delimiter(text: str) -> str:
    """Sniff delimiter from first few lines, falling back to comma."""
    sample = "\n".join(text.splitlines()[:15])
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=[",", "\t", ";", "|"])
        return dialect.delimiter
    except Exception:
        # Heuristic count
        counts = {
            ",": sample.count(","),
            "\t": sample.count("\t"),
            ";": sample.count(";"),
            "|": sample.count("|"),
        }
        best = max(counts, key=counts.get)
        return best if counts[best] > 2 else ","


def parse_csv_rows(text: str, delimiter: str | None = None) -> list[list[str]]:
    """Parse delimited text into clean list of string lists."""
    delim = delimiter or detect_delimiter(text)
    reader = csv.reader(io.StringIO(text), delimiter=delim)
    return [[col.strip() for col in row] for row in reader if any(col.strip() for col in row)]


def is_multi_section_dsr(text: str) -> bool:
    """Check if the text file has multiple explicit sheet or table headers."""
    pattern = r"(?im)^(?:\s*\[\s*(?:sheet|table)?\s*:?\s*([a-z0-9 &_-]+)\s*\]|\s*(?:===+|---+|###+)\s*([a-z0-9 &_-]+)\s*(?:===+|---+|###+)|\s*#\s*(?:sheet|table):\s*([a-z0-9 &_-]+))"
    return len(re.findall(pattern, text)) >= 2


def build_workbook_from_sections(text: str) -> openpyxl.Workbook:
    """
    Parse a multi-section text file into an in-memory openpyxl Workbook.
    Recognizes sections like:
    [Sheet: Booking & Alloted]
    === Leads ===
    # Sheet: Stock & Allotted
    """
    wb = openpyxl.Workbook()
    default_sheet = wb.active

    pattern = r"(?im)^(?:\s*\[\s*(?:sheet|table)?\s*:?\s*([a-z0-9 &_-]+)\s*\]|\s*(?:===+|---+|###+)\s*([a-z0-9 &_-]+)\s*(?:===+|---+|###+)|\s*#\s*(?:sheet|table):\s*([a-z0-9 &_-]+))"

    sections: list[tuple[str, list[str]]] = []
    current_title = "Sheet1"
    current_lines: list[str] = []

    for line in text.splitlines():
        match = re.match(pattern, line)
        if match:
            title = next(g for g in match.groups() if g).strip()
            if current_lines and current_title:
                sections.append((current_title, current_lines))
                current_lines = []
            current_title = title
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_title, current_lines))

    for title, lines in sections:
        ws = wb.create_sheet(title=title)
        delim = detect_delimiter("\n".join(lines[:10]))
        reader = csv.reader(io.StringIO("\n".join(lines)), delimiter=delim)
        for row in reader:
            if any(c.strip() for c in row):
                ws.append(row)

    if default_sheet in wb.worksheets and len(wb.worksheets) > 1:
        wb.remove(default_sheet)

    return wb


def detect_table_type(headers: list[str], explicit_type: str | None = None) -> str:
    """Determine whether a single tabular CSV/TXT represents bookings, leads, stock, or test drives."""
    if explicit_type and explicit_type.lower() in ("booking", "lead", "vehicle", "test_drive", "stock"):
        t = explicit_type.lower()
        return "vehicle" if t == "stock" else t

    norm = [re.sub(r"[^a-z0-9]", "", h.lower()) for h in headers]
    s = " ".join(norm)

    if any(k in s for k in ("chassis", "vin", "enginenumber", "billingdate", "stockstatus", "agingdays")):
        return "vehicle"
    if any(k in s for k in ("testdrive", "tddate", "startkm", "endkm", "distancekm")):
        return "test_drive"
    if any(k in s for k in ("contract", "bookingamount", "deposit", "fulfilment", "crmentry", "alloted")):
        return "booking"
    if any(k in s for k in ("leadtype", "rating", "qualifiedstage", "enquiry", "leadowner")):
        return "lead"

    # Secondary heuristic
    if "booking" in s or "customer" in s:
        return "booking"
    if "lead" in s or "source" in s:
        return "lead"

    return "booking"


def find_column(headers: list[str], *aliases: str) -> int | None:
    """Find index of header matching any of the alias keywords."""
    norm_headers = [re.sub(r"[^a-z0-9]", "", h.lower()) for h in headers]
    for alias in aliases:
        norm_alias = re.sub(r"[^a-z0-9]", "", alias.lower())
        for i, h in enumerate(norm_headers):
            if norm_alias == h or norm_alias in h:
                return i
    return None


def parse_cell_date(val: Any) -> date | None:
    """Parse date from common CSV string formats."""
    d = nz.as_date(val)
    if d:
        return d
    s = str(val or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            continue
    return None


def ingest_text_report(
    content: bytes,
    filename: str,
    period_label: str,
    period_start: date,
    period_end: date,
    uploaded_by: str = "Reporting Agent",
    table_type: str | None = None,
    mode: str = "replace",
) -> dict[str, Any]:
    """
    Main entry point for ingesting CSV and TXT report files.

    A multi-section text DSR is a whole workbook in text form, so it honours
    `mode` exactly as an Excel upload does. A single table (bookings, leads or
    stock) is always ADDED to the month - there is no sensible "replace the
    month" for one table out of twelve - and the result says so in `mode`.
    """
    text = decode_bytes(content)
    if not text.strip():
        raise ValueError("Uploaded report file is empty.")

    # 1. Multi-section DSR Text file
    if is_multi_section_dsr(text):
        wb = build_workbook_from_sections(text)
        with db_connect(autocommit=True) as cx:
            # FIX (2026-10-08): ran on a bare autocommit connection, so a load
            # that failed part-way left reset()'s deletes committed and the
            # month empty. One transaction now, as the Excel upload uses. The
            # upload's chosen mode is passed through too - it was ignored.
            with cx.transaction():
                loader = Loader(cx, wb, period_label, period_start, period_end, mode=mode)
                counts = loader.run()
            return {
                "detected_format": "multi_section_dsr_text",
                "mode": loader.mode,
                "counts": counts,
                "warnings": loader.warnings,
                "sheets_parsed": [ws.title for ws in wb.worksheets],
            }

    # 2. Tabular CSV or Delimited TXT file
    delimiter = detect_delimiter(text)
    rows = parse_csv_rows(text, delimiter=delimiter)
    if not rows:
        raise ValueError("No tabular data found in file.")

    headers = rows[0]
    data_rows = rows[1:]
    kind = detect_table_type(headers, table_type)

    # FIX (2026-10-08): this used autocommit=True, so every row committed on its
    # own and a file that failed on row 200 left 199 rows in the database with
    # no etl_run record of how they got there. Without autocommit the `with`
    # block is one transaction: it commits when the block finishes and rolls
    # the whole file back if anything in it raises.
    with db_connect() as cx:
        # Ensure period exists in dim_period
        p_row = cx.execute("""
            INSERT INTO dim_period (label, period_start, period_end)
            VALUES (%s, %s, %s)
            ON CONFLICT (label) DO UPDATE SET period_start = EXCLUDED.period_start,
                                             period_end = EXCLUDED.period_end
            RETURNING period_id
        """, (period_label, period_start, period_end)).fetchone()
        period_id = p_row[0]

        # The month is activated at the end, through dims.activate_period, once
        # the rows are in - see the note there.

        counts: dict[str, int] = {}
        inserted = 0

        if kind == "booking":
            col_date = find_column(headers, "date", "bookingdate", "dob")
            col_cust = find_column(headers, "customer", "customername", "client", "name")
            col_mobile = find_column(headers, "mobile", "phone", "contact")
            col_cons = find_column(headers, "consultant", "sc", "executive", "salesexec")
            col_model = find_column(headers, "model", "car", "vehicle")
            col_var = find_column(headers, "variant", "trim", "version")
            col_col = find_column(headers, "colour", "color", "exterior")
            col_my = find_column(headers, "modelyear", "my", "year")
            col_stat = find_column(headers, "status", "fulfilment", "fulfilmentstatus")
            col_crm = find_column(headers, "crmentry", "crmdone", "incrm", "crm")
            col_amt = find_column(headers, "amount", "bookingamount", "deposit", "value")
            col_src = find_column(headers, "source", "channel", "leadsource")
            col_notes = find_column(headers, "notes", "remarks", "comment")

            for r in data_rows:
                def get_val(idx: int | None):
                    return r[idx].strip() if idx is not None and idx < len(r) and r[idx].strip() else None

                # PII POLICY (2026-10-08): a phone/email inside the name is cut out.
                cust_name = pii.scrub_text(get_val(col_cust))
                if not cust_name:
                    continue

                b_date = parse_cell_date(get_val(col_date)) or date.today()
                consultant_name = get_val(col_cons)
                consultant_id = dims.resolve_consultant(cx, consultant_name, activate=True) if consultant_name else None
                # FIX (2026-10-08): a row with no model column used to be filed
                # as a TAIGUN booking, and one with no model year as this year's
                # car - figures nobody entered, indistinguishable from real ones.
                # Missing values now stay missing (NULL).
                model_name = get_val(col_model)
                model_id = dims.resolve_model(cx, model_name) if model_name else None
                variant_name = get_val(col_var)
                variant_id = (dims.resolve_variant(cx, model_name, variant_name)
                              if variant_name and model_name else None)
                colour_name = get_val(col_col)
                colour_id = dims.resolve_colour(cx, colour_name) if colour_name else None
                source_name = get_val(col_src)
                source_id = dims.resolve_source(cx, source_name) if source_name else None

                fulfilment = nz.fulfilment_status(get_val(col_stat)) or "BOOKED"
                crm_done = nz.as_bool(get_val(col_crm)) or False
                amount = nz.as_num(get_val(col_amt))
                my = nz.as_int(get_val(col_my))
                # PII POLICY (2026-10-08): the phone is never stored, and one
                # typed into the notes is cut out of them - see etl/pii.py.
                mobile = pii.redact(get_val(col_mobile))
                notes = pii.scrub_text(get_val(col_notes))

                # FIX (2026-10-08): load_period_id is now set on the row. It was
                # left NULL, which the workbook loader reads as "inserted by the
                # load running right now" - so the next workbook upload, for ANY
                # month, could merge these bookings into its own or delete them
                # (load_bookings' de-duplication), and stamp_load() then filed
                # the survivors under that other month. Stamped here, they
                # belong to this month's uploads like any workbook row, and a
                # replace upload of this month is what removes them.
                cx.execute("""
                    INSERT INTO booking (
                        booking_date, customer_name, mobile, source_id,
                        consultant_id, team_id, model_id, variant_id,
                        colour_id, model_year, fulfilment_status,
                        car_origin, crm_entry_done, booking_amount, notes,
                        source_sheet, period_id, is_current_period,
                        origin, entered_by, load_period_id
                    ) VALUES (
                        %s, %s, %s, %s,
                        %s, (SELECT team_id FROM dim_consultant WHERE consultant_id = %s),
                        %s, %s, %s, %s, %s,
                        'FRESH_CAR', %s, %s, %s,
                        %s, %s, false,
                        'WORKBOOK', %s, %s
                    )
                """, (
                    b_date, cust_name, mobile, source_id,
                    consultant_id, consultant_id,
                    model_id, variant_id, colour_id, my, fulfilment,
                    crm_done, amount, notes,
                    f"Uploaded {filename}", period_id,
                    uploaded_by, period_id,
                ))
                inserted += 1

            counts["booking"] = inserted

        elif kind == "lead":
            col_date = find_column(headers, "date", "createdon", "createdat")
            col_name = find_column(headers, "name", "leadname", "customer")
            col_mobile = find_column(headers, "mobile", "phone")
            col_cons = find_column(headers, "consultant", "sc", "leadowner")
            col_model = find_column(headers, "model", "modelofinterest")
            col_src = find_column(headers, "source", "leadtype", "channel")
            col_qual = find_column(headers, "qualified", "stage", "qualifiedstage")
            col_rating = find_column(headers, "rating")

            for r in data_rows:
                def get_val(idx: int | None):
                    return r[idx].strip() if idx is not None and idx < len(r) and r[idx].strip() else None

                # PII POLICY (2026-10-08): a phone/email inside the name is cut out.
                name = pii.scrub_text(get_val(col_name))
                if not name:
                    continue

                l_date = parse_cell_date(get_val(col_date)) or date.today()
                consultant_name = get_val(col_cons)
                consultant_id = dims.resolve_consultant(cx, consultant_name, activate=True) if consultant_name else None
                # FIX (2026-10-08): a lead with no model was recorded as
                # interested in a TAIGUN, every unrated lead as HOT, and the
                # lead's channel was written into lead_type (which holds
                # Retail / Corporate, not a channel). None of that was in the
                # file. Missing values now stay missing.
                model_name = get_val(col_model)
                model_id = dims.resolve_model(cx, nz.model_from_text(model_name)) if model_name else None
                source_name = get_val(col_src)
                source_id = dims.resolve_source(cx, source_name) if source_name else None
                # PII POLICY (2026-10-08): the phone is never stored.
                mobile = pii.redact(get_val(col_mobile))
                qualified = nz.as_bool(get_val(col_qual))
                stage = "Qualified" if qualified else "New"
                rating = get_val(col_rating)

                # FIX (2026-10-08): two provenance problems, the same as the
                # bookings above plus one more. load_period_id was never set
                # (so a later workbook upload claimed these rows), and
                # entered_by WAS set - which db/triggers.sql lead_fill_direct()
                # treats as "typed by a person" and forces origin to MANUAL. So
                # uploaded leads were labelled hand-entered, listed under
                # Recently Recorded, and survived a replace upload of their own
                # month while the bookings from the same file did not. The row
                # is inserted without entered_by, so it stays WORKBOOK, and the
                # uploader's name is written back just after (the trigger only
                # runs on INSERT).
                lead_id = cx.execute("""
                    INSERT INTO lead (
                        lead_name, mobile, source_id,
                        model_of_interest, model_id, consultant_id, rating,
                        qualified_stage, created_at, period_id,
                        is_current_period, origin, load_period_id
                    ) VALUES (
                        %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s,
                        false, 'WORKBOOK', %s
                    )
                    RETURNING lead_id
                """, (
                    name, mobile, source_id,
                    model_name, model_id, consultant_id, rating,
                    stage, l_date, period_id,
                    period_id,
                )).fetchone()[0]
                cx.execute("UPDATE lead SET entered_by = %s WHERE lead_id = %s",
                           (uploaded_by, lead_id))
                inserted += 1

            counts["lead"] = inserted

        elif kind == "vehicle":
            col_chassis = find_column(headers, "chassis", "vin", "chassisnumber")
            col_model = find_column(headers, "model", "car")
            col_var = find_column(headers, "variant", "trim")
            col_col = find_column(headers, "colour", "color")
            col_stat = find_column(headers, "status", "stockstatus")
            col_aging = find_column(headers, "aging", "agingdays", "stockagingdays")
            col_bill = find_column(headers, "billingdate", "billing", "billdate")

            for r in data_rows:
                def get_val(idx: int | None):
                    return r[idx].strip() if idx is not None and idx < len(r) and r[idx].strip() else None

                chassis = nz.chassis(get_val(col_chassis))
                if not chassis:        # blank, or not a chassis number: never a new "car"
                    if get_val(col_chassis):
                        counts["vehicle_skipped_not_chassis"] = counts.get("vehicle_skipped_not_chassis", 0) + 1
                    continue

                # FIX (2026-10-08): a car with no model was stocked as a TAIGUN,
                # with no ageing as 0 days old, and with no billing date as
                # billed today - which also hid it from the 90-day ageing
                # figures. Missing values now stay missing.
                model_name = get_val(col_model)
                model_id = dims.resolve_model(cx, model_name) if model_name else None
                variant_name = get_val(col_var)
                variant_id = (dims.resolve_variant(cx, model_name, variant_name)
                              if variant_name and model_name else None)
                colour_name = get_val(col_col)
                colour_id = dims.resolve_colour(cx, colour_name) if colour_name else None
                status = nz.stock_status(get_val(col_stat)) or "FREESTOCK"
                aging = nz.as_int(get_val(col_aging))
                billing = parse_cell_date(get_val(col_bill))

                cx.execute("""
                    INSERT INTO vehicle (
                        chassis_number, model_id, variant_id, colour_id,
                        billing_date, stock_aging_days, stock_status
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chassis_number) DO UPDATE SET
                        stock_status = EXCLUDED.stock_status,
                        -- FIX (2026-10-08): a file without an ageing column
                        -- used to reset every known car to 0 days; now the
                        -- existing figure is kept when the file has none.
                        stock_aging_days = COALESCE(EXCLUDED.stock_aging_days, vehicle.stock_aging_days),
                        model_id = COALESCE(vehicle.model_id, EXCLUDED.model_id),
                        variant_id = COALESCE(vehicle.variant_id, EXCLUDED.variant_id),
                        colour_id = COALESCE(vehicle.colour_id, EXCLUDED.colour_id)
                """, (chassis, model_id, variant_id, colour_id, billing, aging, status))
                inserted += 1

            counts["vehicle"] = inserted

        # FIX (2026-10-08): this activated the month in dim_period but then
        # realigned is_current_period on only the ONE table it had loaded. A
        # bookings CSV for SEP2026 uploaded while AUG2026 was showing therefore
        # left the dashboard on September's bookings against August's leads.
        # activate_period() realigns every fact table together, the same way a
        # workbook upload does.
        dims.activate_period(cx, period_label)

        return {
            "detected_format": f"delimited_{delimiter}",
            "detected_table": kind,
            # A single table is always added to the month - see the docstring.
            "mode": "append",
            "counts": counts,
            "total_rows_imported": inserted,
        }
