"""
Load a DSR workbook into the `dsr` schema.

    python -m etl.load_dsr                      # loads ./DSR August 2026.xlsx
    python -m etl.load_dsr --file other.xlsx
    python -m etl.load_dsr --period SEP2026 --start 2026-09-01 --end 2026-09-30

The load is idempotent: every table in `dsr` is emptied and rebuilt from the
workbook, so re-running after the sheet is updated is the normal way to refresh.
Reference tables (consultants, models, variants, colours, sources) are discovered
from the data rather than hard-coded, so a new trim or a new joiner appears
automatically.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from datetime import date, datetime
from pathlib import Path

import openpyxl
import psycopg

from . import dimensions as dims
from . import normalize as nz
# PII POLICY (2026-10-08): customer phone, email and address are never stored
# (etl/pii.py). Phone/email/address COLUMNS go through pii.redact(); every
# customer NAME and free-text cell goes through pii.scrub_text(), because the
# CRM export sometimes writes the phone or email into the name field itself
# ("Naresh naresh@...", "Asif 98..."). Names are scrubbed the same way wherever
# they are read, so the joins on customer name (booking <-> allotment, the
# booking de-duplication) still line up.
from . import pii
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DSN = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:postgres@127.0.0.1:5432/elite_dsr",
)
DEFAULT_FILE = Path(__file__).resolve().parent.parent / "DSR August 2026.xlsx"

# Facts rebuilt from the workbook, in dependency order so the foreign keys never
# block a reload. Only WORKBOOK-origin rows are cleared - see reset().
WORKBOOK_FACTS = ["registration", "allotment", "booking", "test_drive", "lead"]

# The workbook tabs the loader reads. The other eight (Free Stock, VW Report,
# Modewise, Comparision...) are pivots of these and are not read.
DSR_TABS = ("Stock & Allotted", "Reg Report", "Leads", "TD Leads", "TD", "Booking & Alloted",
            "Current Month Booking", "Live Booking", "Pending Booking", "Golf & Tiguan R Line Booking",
            "Alloted", "SC Performance", "Book Comm VS Ach", "Daily Tracker")


def _tab_key(name) -> str:
    """A tab name as typed by hand, compared loosely: case, spacing, '&' or
    'and', and the workbook's own two spellings of allotted."""
    t = re.sub(r"\s+", " ", str(name).replace("&", " and ")).strip().casefold()
    return t.replace("alloted", "allotted")


def find_tab(sheetnames, wanted: str) -> str | None:
    """The workbook's own name for a tab, matched loosely; None if it has none."""
    if wanted in sheetnames:
        return wanted
    key = _tab_key(wanted)
    return next((n for n in sheetnames if _tab_key(n) == key), None)


def workbook_problem(wb) -> str | None:
    """Why a workbook cannot be loaded as a month's DSR workbook, in words for
    the person uploading it - or None when it can.

    The dashboard's own Excel export was uploaded to replace a month, and the
    load died on its first tab with "Worksheet Stock & Allotted does not
    exist". An export holds the dashboard's figures, not the month's tabs, and
    cannot be loaded back in - its DSR layout even reuses a few tab names
    (Leads, Daily Tracker) over columns of its own, so every tab is checked."""
    names = list(wb.sheetnames)
    missing = [t for t in DSR_TABS if not find_tab(names, t)]
    if not missing:
        return None
    upload = ("Upload the month's DSR workbook - the one with the Stock & Allotted, "
              "Booking & Alloted, Reg Report and Leads tabs.")
    cover = find_tab(names, "Summary")
    if cover:
        try:
            title = str(wb[cover]["A1"].value or "")
        except Exception:
            title = ""
        if "DSR Export" in title:
            return ("This file is an export from the dashboard - a report of its figures - not a DSR "
                    "workbook, so it cannot be loaded back in. " + upload)
    if len(missing) > len(DSR_TABS) // 2:
        return ("This file is not a DSR workbook: it is missing " + ", ".join(missing)
                + ". A file exported from the dashboard cannot be loaded back in. " + upload)
    return ("This workbook is missing tabs the dashboard reads: " + ", ".join(missing)
            + ". Check they have not been renamed or deleted.")

# Targets belong wholly to the workbook for the period being loaded, so these are
# cleared by period rather than by origin.
PERIOD_TARGETS = [
    "target_daily_tracker", "target_booking_commitment",
    "target_channel_funnel", "target_consultant_scorecard",
]

# Dimensions are never cleared. They are upserted, so re-running is harmless, and
# keeping the rows keeps their surrogate ids stable for anything already
# referencing them. `vehicle` is treated the same way: it upserts on chassis
# number, which is the real identity of the car, so a reload updates the unit in
# place instead of giving it a new id.


class Loader:
    def __init__(self, conn: psycopg.Connection, wb, period_label: str,
                 period_start: date, period_end: date, mode: str = "replace"):
        self.cx = conn
        self.wb = wb
        # "replace" rebuilds the month from this workbook, which is right for a
        # monthly DSR. "append" adds to what is already there, for a dealership
        # uploading a day or a week at a time - the month accumulates instead of
        # being overwritten by its own latest slice.
        self.mode = mode if mode in ("replace", "append") else "replace"
        self.period_label = period_label
        self.period_start = period_start
        self.period_end = period_end
        self.counts: dict[str, int] = {}
        self.warnings: list[str] = []
        # Sheets pulled into memory whole, for the few places that need random
        # access - see grid().
        self._grids: dict[str, list] = {}

        # caches: canonical key -> surrogate id
        self.teams: dict[str, int] = {}
        for name, tid in self.cx.execute("SELECT name, team_id FROM dim_team").fetchall():
            k = nz.team_key(name)
            if k: self.teams[k] = tid
            
        self.consultants: dict[str, int] = {}
        for name, cid in self.cx.execute("SELECT full_name, consultant_id FROM dim_consultant").fetchall():
            k = nz.consultant_key(name)
            if k: self.consultants[k] = cid
            
        self.models: dict[str, int] = {}
        for name, mid in self.cx.execute("SELECT name, model_id FROM dim_model").fetchall():
            k = nz.model_key(name)
            if k: self.models[k] = mid
            
        self.variants: dict[tuple[int, str], int] = {}
        for mid, name, vid in self.cx.execute("SELECT model_id, name, variant_id FROM dim_variant").fetchall():
            k = nz.variant_key(name)
            if k: self.variants[(mid, k)] = vid
            
        self.colours: dict[str, int] = {}
        for name, cid in self.cx.execute("SELECT name, colour_id FROM dim_colour").fetchall():
            k = nz.colour_key(name)
            if k: self.colours[k] = cid
            
        self.sources: dict[str, int] = {}
        for name, sid in self.cx.execute("SELECT name, source_id FROM dim_lead_source").fetchall():
            k = nz.source_key(name)
            if k: self.sources[k[0]] = sid

        self.period_id: int | None = None
        self.vehicle_by_chassis: dict[str, int] = {}
        
        self._updated_variants: set[tuple] = set()
        self._updated_consultants: set[tuple] = set()

    # -- small helpers ------------------------------------------------

    def fast_executemany(self, query, rows, dedup_idx=None):
        import re
        if not rows: return
        
        if dedup_idx is not None:
            # Only rows that actually carry a key can be deduplicated on it. The
            # Leads tab leaves the CRM record id blank for every row, so keying
            # on it collapsed all 367 August enquiries into one - the dashboard
            # then read 1 enquiry against 42 bookings.
            seen, keyless = {}, []
            for row in rows:
                if row[dedup_idx] is None:
                    keyless.append(row)
                elif row[dedup_idx] not in seen:
                    seen[row[dedup_idx]] = row
            rows = list(seen.values()) + keyless
            
        match = re.search(r'(?i)(VALUES\s*)(\([^)]+\))', query)
        if not match:
            self.cx.cursor().executemany(query, rows)
            return
            
        prefix = query[:match.start(2)]
        placeholders = match.group(2)
        suffix = query[match.end(2):]
        
        for i in range(0, len(rows), 1000):
            chunk = rows[i:i+1000]
            values_str = ",".join([placeholders] * len(chunk))
            flat = [v for row in chunk for v in row]
            self.cx.execute(prefix + values_str + suffix, flat)

    def rows(self, sheet: str, header_row: int, key_col: int):
        """
        Yield (row_number, cell_getter) for rows that carry real data.

        Several tabs are pre-numbered far past their content (Reg Report runs its
        No column to 100 but only ~21 rows are filled), so a row only counts when
        its key column is populated.
        """
        ws = self.wb[self._tab(sheet)]
        try:
            ws.reset_dimensions = True
        except AttributeError:
            pass
        for r, row in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
            # No early exit on a run of blanks: the Leads tab alone has a
            # 120-row gap before its last entries, and iter_rows is cheap enough
            # to read the sheet out in full.
            if not row or key_col > len(row) or nz.clean(row[key_col - 1]) is None:
                continue
            yield r, (lambda c, _row=row: _row[c - 1] if c <= len(_row) else None)

    def grid(self, sheet: str) -> list:
        """
        A whole sheet as a list of row tuples, 1-indexed so grid[r] is row r.

        Three tabs need random access (walk down looking for a header, then read
        a column out of rows above and below it), which openpyxl refuses in
        read_only mode. Reading the sheet out once and indexing the list keeps
        that code working and costs nothing: the only sheet that needs it is SC
        Performance, at 28 rows.
        """
        if sheet in self._grids:
            return self._grids[sheet]
        ws = self.wb[self._tab(sheet)]
        # A workbook that under-reports its own dimensions would otherwise be
        # truncated on read - verified row-for-row against normal mode.
        try:
            ws.reset_dimensions = True
        except AttributeError:
            pass                         # normal (non read_only) worksheet
        rows = [()]                      # index 0 unused
        rows.extend(ws.iter_rows(values_only=True))
        self._grids[sheet] = rows
        return rows

    def _tab(self, sheet: str) -> str:
        """The workbook's own name for a tab (see find_tab), or a plain error."""
        name = find_tab(self.wb.sheetnames, sheet)
        if name is None:
            raise ValueError(workbook_problem(self.wb) or f"The workbook has no '{sheet}' tab.")
        return name

    def one(self, sql: str, params=()) -> int:
        return self.cx.execute(sql, params).fetchone()[0]

    # -- reference data ----------------------------------------------

    # -- reference data ----------------------------------------------
    #
    # These wrap etl/dimensions.py, which the write API also uses, so a
    # consultant typed into the dashboard resolves to the same row the loader
    # would have created. The only thing added here is a per-run cache: the
    # loader resolves the same handful of names across thousands of rows.

    def _cached(self, cache: dict, key, resolve):
        if key not in cache:
            cache[key] = resolve()
        return cache[key]

    def team_id(self, label) -> int | None:
        key = nz.team_key(label)
        if not key:
            return None
        return self._cached(self.teams, key, lambda: dims.resolve_team(self.cx, label))

    def consultant_id(self, label, team=None, channel=None) -> int | None:
        key = nz.consultant_key(label)
        if not key:
            return None
        # Cache only the lookup; team and channel still get applied every call,
        # because different tabs carry different pieces of the same person.
        cid = self._cached(self.consultants, key,
                           lambda: dims.resolve_consultant(self.cx, label))
        if team is not None or channel is not None:
            ukey = (cid, team, channel)
            if ukey not in self._updated_consultants:
                dims.resolve_consultant(self.cx, label, team=team, channel=channel)
                self._updated_consultants.add(ukey)
        return cid

    def model_id(self, label) -> int | None:
        key = nz.model_key(label)
        if not key:
            return None
        return self._cached(self.models, key, lambda: dims.resolve_model(self.cx, label))

    def variant_id(self, model_label, variant_label,
                   long_text=None, model_code=None) -> int | None:
        mid = self.model_id(model_label)
        vkey = nz.variant_key(variant_label)
        if not mid or not vkey:
            return None
        vid = self._cached(
            self.variants, (mid, vkey),
            lambda: dims.resolve_variant(self.cx, model_label, variant_label,
                                         long_text, model_code))
        # The booking tabs name the trim but not the factory text; the stock tabs
        # carry both. Backfill whichever arrives second.
        if long_text or model_code:
            ukey = (vid, nz.clean(long_text), nz.upper(model_code))
            if ukey not in self._updated_variants:
                self.cx.execute(
                    "UPDATE dim_variant SET long_model_text = COALESCE(long_model_text, %s), "
                    "model_code = COALESCE(model_code, %s) WHERE variant_id = %s",
                    (nz.clean(long_text), nz.upper(model_code), vid))
                self._updated_variants.add(ukey)
        return vid

    def colour_id(self, label, code=None) -> int | None:
        key = nz.colour_key(label)
        if not key:
            return None
        return self._cached(self.colours, key,
                            lambda: dims.resolve_colour(self.cx, label, code))

    def source_id(self, label) -> int | None:
        resolved = nz.source_key(label)
        if not resolved:
            return None
        return self._cached(self.sources, resolved[0],
                            lambda: dims.resolve_source(self.cx, label))

    # =================================================================
    # Load steps
    # =================================================================

    def load_period(self):
        self.period_id = self.one(
            "INSERT INTO dim_period (label, period_start, period_end) VALUES (%s, %s, %s) "
            "ON CONFLICT (label) DO UPDATE SET period_start = EXCLUDED.period_start, "
            "                                 period_end = EXCLUDED.period_end "
            "RETURNING period_id",
            (self.period_label, self.period_start, self.period_end))
        # Loading a workbook is a statement about which month matters, so the
        # dashboard follows it. Cleared first: only one period may be active.
        self.cx.execute("UPDATE dim_period SET is_active = false WHERE is_active")
        self.cx.execute("UPDATE dim_period SET is_active = true WHERE period_id = %s",
                        (self.period_id,))

    def load_teams_and_channels(self):
        """
        Derive each consultant's team and primary channel from the data.

        Team comes from the TEAM column on Booking & Alloted; primary channel from
        the LEAD TYPE column on SC Performance. Both are read before the fact tables
        so consultant rows are complete by the time bookings reference them.
        """
        for _, cell in self.rows("Booking & Alloted", 1, 11):
            self.consultant_id(cell(12), team=cell(13))

        g = self.grid("SC Performance")
        for r in range(5, len(g)):
            name, lead_type = gcell(g, r, 2), nz.upper(gcell(g, r, 3))
            if not nz.consultant_key(name) or not lead_type:
                continue
            channel = {"WALKIN": "WALKIN", "TELE": "TELE"}.get(lead_type)
            if channel:
                self.consultant_id(name, channel=channel)

        # Anyone appearing in the August book is currently on the floor; the rest
        # (2024-era staff reachable only through the historical lead dump) stay inactive.
        self.cx.execute("""
            UPDATE dim_consultant SET is_active = true
            WHERE consultant_id IN (
                SELECT consultant_id FROM booking WHERE consultant_id IS NOT NULL
                UNION SELECT consultant_id FROM dim_consultant WHERE primary_channel IS NOT NULL
            )""")

    def load_vehicles(self):
        """
        Stock & Allotted is the live inventory; Reg Report adds units that have
        already left stock. Both key on chassis number, so the second pass upserts.
        """
        print("loading vehicles...")
        rows = []
        not_chassis = 0
        for sheet, header, cols in (
            ("Stock & Allotted", 1, dict(chassis=3, comm=2, engine=4, model_code=5,
                                         long=6, variant=7, my=9, obd=10, options=11,
                                         colour_code=12, colour=13, model=14,
                                         billing=15, received=16, aging=17,
                                         status=18, nadcon=24)),
            ("Reg Report", 2, dict(chassis=3, comm=2, engine=4, model_code=5,
                                   long=6, variant=7, my=9, obd=10, options=10,
                                   colour_code=11, colour=12, model=13,
                                   billing=14, received=15, aging=16,
                                   status=17, nadcon=23)),
        ):
            for _, cell in self.rows(sheet, header, cols["chassis"]):
                chassis = nz.chassis(cell(cols["chassis"]))
                if not chassis:
                    # Not a chassis number - a name, say, in a sheet laid out
                    # differently. Its other columns cannot be trusted either,
                    # so the row is left out rather than made into a car.
                    not_chassis += 1
                    continue
                model_label = cell(cols["model"])
                vid = self.variant_id(model_label, cell(cols["variant"]),
                                      long_text=cell(cols["long"]),
                                      model_code=cell(cols["model_code"]))
                row = (
                    chassis,
                    nz.clean(cell(cols["comm"])),
                    nz.upper(cell(cols["engine"])),
                    self.model_id(model_label),
                    vid,
                    self.colour_id(cell(cols["colour"]), cell(cols["colour_code"])),
                    nz.upper(cell(cols["model_code"])),
                    nz.clean(cell(cols["long"])),
                    nz.as_int(cell(cols["my"])),
                    nz.upper(cell(cols["obd"])),
                    nz.clean(cell(cols["options"])),
                    nz.as_date(cell(cols["billing"])),
                    nz.as_date(cell(cols["received"])),
                    nz.as_int(cell(cols["aging"])),
                    nz.stock_status(cell(cols["status"])) or "FREESTOCK",
                    nz.as_date(cell(cols["nadcon"])),
                )
                rows.append(row)
        if not_chassis:
            self.warnings.append(
                f"Stock: {not_chassis} row(s) skipped - the chassis column held something other "
                f"than a chassis number (a name, or a shifted column)")

        if rows:
            self.fast_executemany("""
                INSERT INTO vehicle (chassis_number, commission_no, engine_number,
                    model_id, variant_id, colour_id, model_code, long_model_text,
                    model_year, obd, options, billing_date, stock_received_date,
                    stock_aging_days, stock_status, nadcon_retail_date)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (chassis_number) DO UPDATE SET
                    -- Reg Report is the later snapshot for units it mentions,
                    -- so its status wins; everything else is only backfilled.
                    stock_status = EXCLUDED.stock_status,
                    commission_no = COALESCE(vehicle.commission_no, EXCLUDED.commission_no),
                    engine_number = COALESCE(vehicle.engine_number, EXCLUDED.engine_number),
                    colour_id = COALESCE(vehicle.colour_id, EXCLUDED.colour_id),
                    variant_id = COALESCE(vehicle.variant_id, EXCLUDED.variant_id),
                    nadcon_retail_date = COALESCE(vehicle.nadcon_retail_date, EXCLUDED.nadcon_retail_date)
                """, rows, dedup_idx=0)
        for chassis, vid in self.cx.execute(
                "SELECT chassis_number, vehicle_id FROM vehicle").fetchall():
            self.vehicle_by_chassis[chassis] = vid
        self.counts["vehicle"] = self.one("SELECT count(*) FROM vehicle")

    def load_leads(self):
        """
        The Leads tab is the August enquiry book (thin - the CRM export only filled
        date, name, source and model of interest). TD Leads is a full 2024 dump kept
        for year-on-year comparison and flagged is_current_period = false.
        """
        print("loading leads...")
        rows = []
        for sheet, current in (("Leads", True), ("TD Leads", False)):
            key_col = 5 if sheet == "Leads" else 2
            for _, cell in self.rows(sheet, 1, key_col):
                created = nz.as_datetime(cell(2))
                # PII POLICY (2026-10-08): Mobile (col 7) and Email (col 8) are
                # never stored - see etl/pii.py. The TD Leads tab alone carries
                # ~1,800 of each.
                rows.append((
                    nz.clean(cell(1)), created, pii.scrub_text(nz.clean(cell(5))), pii.redact(cell(7)),
                    pii.redact(cell(8)), self.source_id(cell(9)), nz.clean(cell(6)),
                    nz.clean(cell(10)), nz.clean(cell(11)), nz.clean(cell(14)),
                    self.model_id(nz.model_from_text(cell(10))),
                    nz.clean(cell(15)), self.consultant_id(cell(15)),
                    nz.clean(cell(16)), nz.clean(cell(17)), nz.clean(cell(35)),
                    nz.as_bool(cell(25)), nz.as_bool(cell(26)), nz.clean(cell(28)),
                    nz.clean(cell(4)), self.period_id if current else None, current,
                ))
        
        if rows:
            self.fast_executemany("""
                INSERT INTO lead (lead_record_id, created_at, lead_name, mobile, email,
                    source_id, lead_type, model_of_interest, variant_of_interest,
                    colour_of_interest, model_id, lead_owner, consultant_id,
                    lead_status, rating, qualified_stage, test_drive_given,
                    trade_in, trade_in_vehicle, dealership, period_id, is_current_period)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, rows, dedup_idx=0)
        self.counts["lead"] = self.one("SELECT count(*) FROM lead")

    def load_test_drives(self):
        print("loading test drives...")
        rows = []
        for _, cell in self.rows("TD", 1, 8):
            # PII POLICY (2026-10-08): Mobile No (col 4) and Email (col 5) are
            # never stored - see etl/pii.py.
            rows.append((
                nz.upper(cell(8)), nz.clean(cell(16)), pii.scrub_text(nz.clean(cell(1))),
                pii.redact(cell(4)), pii.redact(cell(5)), self.source_id(cell(3)),
                nz.clean(cell(6)), nz.clean(cell(7)),
                self.model_id(nz.model_from_text(cell(7))), nz.upper(cell(9)),
                nz.as_int(cell(10)), nz.as_int(cell(11)), nz.as_int(cell(12)),
                nz.as_date(cell(13)), nz.clean(cell(14)), nz.as_datetime(cell(15)),
                nz.clean(cell(17)), self.consultant_id(cell(18)),
            ))
        
        if rows:
            self.fast_executemany("""
                INSERT INTO test_drive (test_drive_number, lead_record_id, lead_name,
                    mobile, email, source_id, stage, model_of_interest, model_id,
                    model_code, start_km, end_km, total_distance_km, td_date, status,
                    created_at, outlet, consultant_id)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (test_drive_number) DO NOTHING
                """, rows, dedup_idx=0)
        self.counts["test_drive"] = self.one("SELECT count(*) FROM test_drive")

    def load_bookings(self):
        """
        Five tabs describe the order book from different angles. Each row keeps its
        source_sheet, and only Current Month Booking is flagged as the August book,
        so `is_current_period` is the safe filter for month numbers while the other
        tabs stay available as the live/pending/carry-over views the floor uses.
        """
        print("loading bookings...")
        booking_tabs = [
            ("Current Month Booking", 1, True, [18]),
            ("Live Booking", 2, False, [15]),
            ("Pending Booking", 1, False, [17, 18]),
            ("Golf & Tiguan R Line Booking", 1, False, [18]),
        ]
        rows_main = []
        for sheet, header, current, note_cols in booking_tabs:
            for _, cell in self.rows(sheet, header, 6):
                # PII POLICY (2026-10-08): MOBILENO (col 7) is never stored, and
                # a phone or email typed into the remarks columns is cut out of
                # them - see etl/pii.py.
                notes = pii.scrub_text(" | ".join(
                    n for n in (nz.clean(cell(c)) for c in note_cols) if n) or None)
                model_label, variant_label = cell(8), cell(9)
                rows_main.append((
                    nz.as_date(cell(2)), nz.clean(cell(3)), self.source_id(cell(4)),
                    self.consultant_id(cell(5)), pii.scrub_text(nz.clean(cell(6))), pii.redact(cell(7)),
                    self.model_id(model_label),
                    self.variant_id(model_label, variant_label, long_text=cell(11)),
                    self.colour_id(cell(12)), nz.as_int(cell(10)), nz.clean(cell(11)),
                    nz.fulfilment_status(cell(13)), nz.car_origin(cell(14)),
                    nz.as_bool(cell(15)), nz.as_num(cell(16)),
                    nz.as_bool(cell(17)) if sheet != "Pending Booking" else None,
                    notes, sheet, self.period_id if current else None, current,
                ))

        if rows_main:
            self.fast_executemany("""
                INSERT INTO booking (booking_date, contract_no, source_id,
                    consultant_id, customer_name, mobile, model_id, variant_id,
                    colour_id, model_year, long_model_text, fulfilment_status,
                    car_origin, crm_entry_done, booking_amount, booking_amount_receipted,
                    notes, source_sheet, period_id, is_current_period)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, rows_main, dedup_idx=4)

        rows_alloted = []
        for _, cell in self.rows("Booking & Alloted", 1, 11):
            chassis = nz.upper(cell(8))
            model_label, variant_label = cell(5), cell(6)
            rows_alloted.append((
                nz.as_date(cell(14)) or nz.as_date(cell(3)), nz.clean(cell(2)),
                self.consultant_id(cell(12), team=cell(13)), self.team_id(cell(13)),
                pii.scrub_text(nz.clean(cell(11))), self.model_id(model_label),
                self.variant_id(model_label, variant_label),
                self.colour_id(cell(7)), nz.as_int(cell(4)),
                nz.fulfilment_status(cell(10)), nz.as_int(cell(16)),
                self.vehicle_by_chassis.get(chassis), "Booking & Alloted",
                None, False,
            ))
            
        if rows_alloted:
            self.fast_executemany("""
                INSERT INTO booking (booking_date, invoice_ref, consultant_id, team_id,
                    customer_name, model_id, variant_id, colour_id, model_year,
                    fulfilment_status, ageing_days, vehicle_id, source_sheet,
                    period_id, is_current_period)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, rows_alloted, dedup_idx=4)
                
        # Deduplicate bookings: the same customer can appear on several tabs
        # (Live vs Alloted), so the older row is merged into the newer one and
        # then removed.
        #
        # Both statements are confined to rows THIS run inserted. They used to
        # match on customer name across the whole table, so loading a second
        # month deleted the first month's bookings for every name the two
        # workbooks had in common - which is how an October test emptied
        # August. reset() has already cleared this period's previous rows, so
        # "load_period_id IS NULL" is exactly this load's output; stamp_load()
        # claims them at the end of run().
        #
        # FIX (2026-10-08): this used to delete HAND-ENTERED bookings. Rows typed
        # on the dashboard (origin = MANUAL) are never stamped with
        # load_period_id - stamp_load() only claims WORKBOOK rows - so they
        # always passed the "load_period_id IS NULL" test. A manual booking
        # whose customer name matched a workbook row was merged into it and
        # deleted, and two manual bookings for the same customer (one person,
        # two cars) collapsed into one, on every upload. Reproduced: a reload
        # deleted 2 of 3 manual bookings. Both statements are now confined to
        # WORKBOOK rows, which is what "this load's output" was meant to be.
        self.cx.execute("""
            UPDATE booking b1 
            SET 
                is_current_period = b1.is_current_period OR b2.is_current_period,
                -- period_id has to come across too. The survivor is the row with
                -- the higher id (Booking & Alloted), which carries no period,
                -- while the row being merged away is the Current Month Booking
                -- entry that does. Without this the merged booking ends up with
                -- period_id NULL, activate_period then recomputes
                -- is_current_period from that NULL, and the month reports zero
                -- bookings against a full order book.
                period_id = COALESCE(b1.period_id, b2.period_id),
                contract_no = COALESCE(b1.contract_no, b2.contract_no),
                source_id = COALESCE(b1.source_id, b2.source_id),
                mobile = COALESCE(b1.mobile, b2.mobile),
                long_model_text = COALESCE(b1.long_model_text, b2.long_model_text),
                car_origin = COALESCE(b1.car_origin, b2.car_origin),
                crm_entry_done = COALESCE(b1.crm_entry_done, b2.crm_entry_done),
                booking_amount = COALESCE(b1.booking_amount, b2.booking_amount),
                booking_amount_receipted = COALESCE(b1.booking_amount_receipted, b2.booking_amount_receipted),
                notes = COALESCE(b1.notes, b2.notes)
            FROM booking b2
            WHERE upper(b1.customer_name) = upper(b2.customer_name)
              AND b1.booking_id > b2.booking_id
              AND b1.load_period_id IS NULL AND b2.load_period_id IS NULL
              AND b1.origin = 'WORKBOOK' AND b2.origin = 'WORKBOOK';

            DELETE FROM booking a USING booking b
            WHERE upper(a.customer_name) = upper(b.customer_name)
              AND a.booking_id < b.booking_id
              AND a.load_period_id IS NULL AND b.load_period_id IS NULL
              AND a.origin = 'WORKBOOK' AND b.origin = 'WORKBOOK'
        """)
        
        self.counts["booking"] = self.one("SELECT count(*) FROM booking")

    def load_allotments(self):
        """
        The Alloted tab names the customer and the model but not the chassis, so the
        vehicle is matched back through Stock & Allotted on customer name.
        """
        matched = 0
        rows = []
        
        booking_by_customer = {
            name: bid for name, bid in self.cx.execute(
                "SELECT upper(customer_name), booking_id FROM booking ORDER BY is_current_period ASC"
            ).fetchall() if name
        }
        
        vehicle_by_commission = {
            comm: vid for comm, vid in self.cx.execute(
                "SELECT commission_no, vehicle_id FROM vehicle WHERE commission_no IS NOT NULL"
            ).fetchall() if comm
        }

        for _, cell in self.rows("Alloted", 1, 5):
            customer = nz.upper(pii.scrub_text(nz.clean(cell(5))))
            commission = nz.clean(cell(1))
            vid = vehicle_by_commission.get(commission) if commission else None
            matched += 1 if vid else 0
            bid = booking_by_customer.get(customer) if customer else None
            
            rows.append((
                vid, bid, pii.scrub_text(nz.clean(cell(5))),
                self.consultant_id(cell(6)), nz.clean(cell(2)),
                nz.colour_key(cell(3)), nz.as_int(cell(4)), nz.as_date(cell(7)),
                nz.as_int(cell(8)), nz.upper(cell(9)), nz.upper(cell(10)),
                # PII POLICY (2026-10-08): free-text remarks, phone/email cut out.
                pii.scrub_text(nz.clean(cell(11)))
            ))
            
        if rows:
            self.fast_executemany("""
                INSERT INTO allotment (vehicle_id, booking_id, customer_name,
                    consultant_id, long_model_text, colour, stock_aging_days,
                    allotted_date, tat_days, vin, obd, remarks)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, rows)
                
        total = self.one("SELECT count(*) FROM allotment")
        self.counts["allotment"] = total
        if total and matched < total:
            self.warnings.append(
                f"allotment: {total - matched} of {total} rows could not be matched to "
                "a vehicle (the Alloted tab has no chassis column)")

    def load_registrations(self):
        print("loading registrations...")
        rows = []
        for _, cell in self.rows("Reg Report", 2, 3):
            chassis = nz.upper(cell(3))
            # PII POLICY (2026-10-08): Contact No (col 24), ADDRESS (col 46) and
            # EMAIL ID (col 47) are never stored - see etl/pii.py.
            rows.append((
                self.vehicle_by_chassis.get(chassis), chassis, pii.scrub_text(nz.clean(cell(18))),
                self.consultant_id(cell(19)), self.source_id(cell(20)),
                nz.upper(cell(17)), nz.as_date(cell(21)), nz.as_date(cell(22)),
                nz.as_date(cell(23)), pii.redact(cell(24)), pii.redact(cell(46)),
                pii.redact(cell(47)), pii.scrub_text(nz.clean(cell(25))), nz.as_date(cell(26)),
                nz.as_date(cell(27)), nz.as_time(cell(28)), nz.as_date(cell(29)),
                nz.as_date(cell(30)), nz.as_date(cell(31)), nz.upper(cell(32)),
                nz.clean(cell(33)), nz.as_date(cell(34)), nz.upper(cell(35)),
                nz.upper(cell(36)), nz.as_bool_lease(cell(37)), nz.as_bool(cell(38)),
                nz.as_bool(cell(39)), nz.as_bool(cell(40)), nz.as_bool(cell(41)),
                nz.as_bool(cell(42)), nz.as_num(cell(43)), nz.clean(cell(44)),
                nz.as_num(cell(45)),
            ))
            
        if rows:
            self.fast_executemany("""
                INSERT INTO registration (vehicle_id, chassis_number, customer_name,
                    consultant_id, source_id, status, booking_date, allotted_date,
                    nadcon_retail_date, contact_no, address, email,
                    nadcon_punched_customer, folder_lined_up_on,
                    folder_given_to_accounts_on, time_given, folder_sent_to_ho,
                    invoice_date, registration_date, registration_no, voiw_id,
                    delivery_date, finance_type, bank, has_insurance,
                    has_extended_warranty, has_service_value_package, is_corporate,
                    dwa, dwa_actual, accessories, vw_offers, elite_discount)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                """, rows, dedup_idx=1)
        self.counts["registration"] = self.one("SELECT count(*) FROM registration")

    def load_scorecards(self):
        """
        SC Performance: each consultant occupies two rows - their primary channel and
        a catch-all second row - interleaved with team subtotals and a grand total.
        A row that names a person starts a new block; the row after it, which has no
        name, is that person's secondary channel.
        """
        g = self.grid("SC Performance")
        cols = dict(leads_target=4, total_leads=5, leads_qualified=6, td_target=7,
                    td_achieved=8, booking_target=10, booking_achieved=11,
                    booking_achieved_total=12, retail_target=14, retail_achieved=15,
                    retail_achieved_total=16, finance_target=18, finance_achieved=19,
                    insurance_target=21, insurance_achieved=22, ew_target=24,
                    ew_achieved=25, svp=27, dwa_eva=28, dwa_achieved=29,
                    taigun_target=30, taigun_achieved=31, punched_vin_target=32,
                    punched_vin_achieved=33, referral_target=34, referral_achieved=35,
                    cancelled=36, allotted=37, coverage=38)
        field_names = list(cols)
        current_label = None

        for r in range(5, len(g)):
            raw_label = nz.clean(gcell(g, r, 2)) or nz.clean(gcell(g, r, 1))
            lead_type = nz.clean(gcell(g, r, 3))
            has_numbers = any(
                nz.as_num(gcell(g, r, c)) is not None for c in cols.values())
            if not has_numbers:
                continue
            # Row 30 onwards is the channel roll-up block, handled separately.
            if raw_label and raw_label.lower() in {"total leads", "qualified leads",
                                                   "booking", "%"}:
                continue

            if raw_label:
                current_label = raw_label
                is_primary = True
            else:
                is_primary = False          # continuation row for the label above
            if not current_label:
                continue

            upper_label = current_label.upper()
            if upper_label.startswith("TOTAL"):
                row_kind = "GRAND_TOTAL"
            elif upper_label.startswith(("S/R TEAM", "FIELD TEAM")):
                row_kind = "TEAM_TOTAL"
            elif nz.consultant_key(current_label):
                row_kind = "CONSULTANT"
            else:
                row_kind = "OTHER"          # Workshop, Co-Dealer, Javeed

            values = [nz.as_num(gcell(g, r, cols[f])) for f in field_names]
            self.cx.execute(f"""
                INSERT INTO target_consultant_scorecard
                    (period_id, consultant_id, row_label, row_kind, lead_type,
                     is_primary_channel, {", ".join(field_names)})
                VALUES ({", ".join(["%s"] * (6 + len(field_names)))})
                ON CONFLICT (period_id, row_label, COALESCE(lead_type,'')) DO NOTHING
                """, [self.period_id, self.consultant_id(current_label), current_label,
                      row_kind, lead_type, is_primary, *values])
        self.counts["target_consultant_scorecard"] = self.one(
            "SELECT count(*) FROM target_consultant_scorecard")

    def load_channel_funnel(self):
        """Channel roll-up at the foot of SC Performance (rows 30-35)."""
        g = self.grid("SC Performance")
        header_row = None
        for r in range(28, len(g)):
            if nz.upper(gcell(g, r, 3)) == "CRM":
                header_row = r
                break
        if header_row is None:
            self.warnings.append("SC Performance: channel roll-up block not found")
            return

        metric_rows = {}
        for r in range(header_row + 1, min(header_row + 8, len(g))):
            label = (nz.clean(gcell(g, r, 2)) or "").lower()
            if label in {"total leads", "qualified leads", "booking"}:
                metric_rows[label] = r

        for c in range(3, gwidth(g) + 1):
            channel = nz.upper(gcell(g, header_row, c))
            if not channel:
                continue
            self.cx.execute("""
                INSERT INTO target_channel_funnel
                    (period_id, channel, total_leads, qualified_leads, bookings)
                VALUES (%s,%s,%s,%s,%s)
                ON CONFLICT (period_id, channel) DO NOTHING
                """, (
                self.period_id, channel,
                nz.as_int(gcell(g, metric_rows["total leads"], c))
                if "total leads" in metric_rows else None,
                nz.as_int(gcell(g, metric_rows["qualified leads"], c))
                if "qualified leads" in metric_rows else None,
                nz.as_int(gcell(g, metric_rows["booking"], c))
                if "booking" in metric_rows else None,
            ))
        self.counts["target_channel_funnel"] = self.one(
            "SELECT count(*) FROM target_channel_funnel")

    def load_booking_commitments(self):
        """Book Comm VS Ach: three week windows, committed vs achieved."""
        g = self.grid("Book Comm VS Ach")
        windows = []
        for c in range(2, gwidth(g) + 1, 2):
            label = nz.upper(gcell(g, 2, c))
            if label:
                windows.append((label, c, c + 1))
        for r in range(3, len(g)):
            label = nz.upper(gcell(g, r, 1))
            if not label:
                continue
            for window, ccol, acol in windows:
                committed = nz.as_num(gcell(g, r, ccol))
                achieved = nz.as_num(gcell(g, r, acol))
                if committed is None and achieved is None:
                    continue
                self.cx.execute("""
                    INSERT INTO target_booking_commitment
                        (period_id, consultant_label, window_label, committed, achieved)
                    VALUES (%s,%s,%s,%s,%s)
                    ON CONFLICT (period_id, consultant_label, window_label) DO NOTHING
                    """, (self.period_id, label, window, committed, achieved))
        self.counts["target_booking_commitment"] = self.one(
            "SELECT count(*) FROM target_booking_commitment")

    def load_daily_tracker(self):
        """
        Daily Tracker is a wide grid of channel blocks. The leftmost twelve columns
        are the same overall summary under every block header, so those are what get
        loaded, one set of rows per block.

        Both blocks are kept because they disagree - the upper block gives AKHILESH an
        enquiry target of 63, the lower one 45 - and silently picking a winner would
        hide that. Views read BLOCK_2, the block with the full roster and team
        subtotals; BLOCK_1 is retained for audit.
        """
        g = self.grid("Daily Tracker")
        header_rows = [r for r in range(1, len(g))
                       if nz.upper(gcell(g, r, 1)) == "SC NAME"]
        for block_no, header in enumerate(header_rows, start=1):
            end = header_rows[block_no] if block_no < len(header_rows) else len(g)
            for r in range(header + 1, end):
                label = nz.upper(gcell(g, r, 1))
                if not label:
                    continue
                self.cx.execute("""
                    INSERT INTO target_daily_tracker (period_id, consultant_label,
                        block_label, enq_target, enq_achieved, booking_target,
                        booking_achieved, td_target, td_achieved, retail_target,
                        retail_achieved, live_booking)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """, (
                    self.period_id, label, f"BLOCK_{block_no}",
                    nz.as_num(gcell(g, r, 2)), nz.as_num(gcell(g, r, 3)),
                    nz.as_num(gcell(g, r, 4)), nz.as_num(gcell(g, r, 5)),
                    nz.as_num(gcell(g, r, 7)), nz.as_num(gcell(g, r, 8)),
                    nz.as_num(gcell(g, r, 10)), nz.as_num(gcell(g, r, 11)),
                    nz.as_num(gcell(g, r, 12)),
                ))
        self.counts["target_daily_tracker"] = self.one(
            "SELECT count(*) FROM target_daily_tracker")

    def link_bookings_to_vehicles(self):
        """
        Close the loop between the order book and inventory using the allotment rows,
        so a booking can be answered with "your car is chassis X" rather than a model name.
        """
        updated = self.cx.execute("""
            UPDATE booking b SET vehicle_id = a.vehicle_id
            FROM allotment a
            WHERE a.booking_id = b.booking_id
              AND a.vehicle_id IS NOT NULL
              AND b.vehicle_id IS NULL
            """).rowcount
        self.counts["booking_vehicle_links"] = updated

    # -----------------------------------------------------------------

    # The primary key of each fact table, and the columns that make a row the
    # same real-world event. Identity, not equality: two different customers
    # can share a name, but the same customer, car and date on two rows is the
    # same booking uploaded twice.
    _PKS = {
        "lead": "lead_id", "booking": "booking_id", "test_drive": "test_drive_id",
        "allotment": "allotment_id", "registration": "registration_id",
    }
    _IDENTITY = {
        "lead":        ["lead_name", "mobile", "created_at", "model_of_interest"],
        "booking":     ["customer_name", "mobile", "booking_date", "model_id", "variant_id"],
        "test_drive":  ["lead_name", "mobile", "td_date", "model_of_interest"],
        # FIX (2026-10-08): was ["vehicle_id", "booking_id"]. booking_id is a
        # surrogate key, and an append inserts the month's bookings again with
        # NEW ids before they are de-duplicated - so an allotment re-read from
        # the same file pointed at a different booking_id and never matched
        # its first copy. Appending the August workbook twice left 31
        # allotments for 20 (found while testing the fixes above). These are
        # the columns the Alloted tab itself carries.
        "allotment":   ["vehicle_id", "customer_name", "allotted_date", "long_model_text"],
        "registration": ["customer_name", "chassis_number"],
    }

    def _pk(self, table: str) -> str:
        return self._PKS[table]

    def _dedupe_appended(self) -> None:
        """
        Drop rows this append added that already existed.

        Appending is for a dealership uploading a day or a week at a time, and
        the obvious accident is uploading the same slice twice - a double click,
        a retry after a timeout, the same file sent on Monday and again on
        Tuesday. Without this that silently doubles the month.

        Only rows created by THIS load are considered (id above the mark taken
        in reset()), and one is removed only when an identical row already sat
        below the mark. A genuinely new row is never touched.
        """
        marks = getattr(self, "_marks", None)
        if not marks:
            return
        for table, mark in marks.items():
            cols = self._IDENTITY.get(table)
            if not cols:
                continue
            pk = self._pk(table)
            match = " AND ".join(
                f"(new.{c} IS NOT DISTINCT FROM old.{c})" for c in cols)

            # Only rows belonging to the month being loaded count as the "same
            # row". Compared across the whole table, appending the August
            # workbook into OCT2026 found all 2,154 of its leads already
            # present under AUG2026 and deleted every one, leaving the new
            # month with nothing but its targets. The guard is for the same
            # slice uploaded twice into the SAME month, not for the same data
            # legitimately filed under two.
            params = [mark, mark]
            if table in ("lead", "booking"):
                scope = f" AND (old.period_id IS NOT DISTINCT FROM new.period_id)"
            else:
                # These three carry no business period. load_period_id records
                # which load produced a row, and stamp_load() sets it after
                # this runs - so rows from an earlier load into this same month
                # already carry it, and the ones just added are still NULL.
                scope = " AND old.load_period_id IS NOT DISTINCT FROM %s"
                params.append(self.period_id)

            removed = self.cx.execute(f"""
                DELETE FROM {table} new
                 WHERE new.{pk} > %s
                   AND new.origin = 'WORKBOOK'
                   AND EXISTS (SELECT 1 FROM {table} old
                                WHERE old.{pk} <= %s AND {match}{scope})
            """, tuple(params)).rowcount
            if removed:
                self.counts[f"{table}_already_present"] = removed

    def reset(self):
        """
        Clear what THIS load is about to rebuild - this period, and nothing else.

        Two things used to go wrong here. `test_drive`, `allotment` and
        `registration` carry no period, so they were cleared with a bare
        `WHERE origin = 'WORKBOOK'` - every month's rows, on every load. And
        booking/lead swept `period_id IS NULL` too, which is where the
        carry-over tabs live, so one month's upload took another month's
        carry-over with it. Loading an October file therefore emptied August.

        Every row now records the period whose load produced it in
        `load_period_id`, independently of the business `period_id` the views
        filter on, so a reload can delete exactly its own previous output.
        Rows the dealership typed in (origin = 'MANUAL') are never touched.
        """
        if self.mode == "append":
            # Nothing is cleared. The high-water marks below are what lets the
            # append de-duplicate itself afterwards: anything this load adds
            # that is identical to a row already present gets dropped again, so
            # re-uploading the same file is harmless rather than doubling the
            # month. Without that, one accidental second click silently doubles
            # every figure on the sheet.
            self._marks = {
                t: (self.one(f"SELECT COALESCE(max({self._pk(t)}), 0) FROM {t}"))
                for t in WORKBOOK_FACTS
            }
            self.counts["mode"] = "append"
            return

        for table in WORKBOOK_FACTS:
            deleted = self.cx.execute(
                f"DELETE FROM {table} "
                f"WHERE origin = 'WORKBOOK' AND load_period_id = %s",
                (self.period_id,)).rowcount
            if deleted:
                self.counts[f"{table}_replaced"] = deleted

        for table in PERIOD_TARGETS:
            self.cx.execute(f"DELETE FROM {table} WHERE period_id = %s",
                            (self.period_id,))

        kept = self.one("SELECT count(*) FROM booking WHERE origin = 'MANUAL'")
        if kept:
            self.warnings.append(
                f"kept {kept} manually entered booking(s) through the reload")

    def stamp_load(self):
        """
        Mark everything this run just wrote with the period that wrote it.

        Done once at the end rather than threaded through every INSERT: the
        fact loaders each build their own column lists, and adding one more to
        five of them is five more places for the next person to forget.
        """
        for table in WORKBOOK_FACTS:
            self.cx.execute(
                f"UPDATE {table} SET load_period_id = %s "
                f"WHERE origin = 'WORKBOOK' AND load_period_id IS NULL",
                (self.period_id,))

    def run(self):
        self.cx.execute("SET search_path = dsr, public")
        self.load_period()
        self.reset()
        self.load_vehicles()
        self.load_teams_and_channels()
        self.load_leads()
        self.load_test_drives()
        self.load_bookings()
        self.load_allotments()
        self.load_registrations()
        self.load_scorecards()
        self.load_channel_funnel()
        self.load_booking_commitments()
        self.load_daily_tracker()
        if self.mode == "append":
            self._dedupe_appended()
        self.link_bookings_to_vehicles()
        self.stamp_load()
        # load_period() flips dim_period.is_active, but the fact tables carry
        # their own is_current_period flag and every headline view filters on
        # it. Without this the previous month stays flagged current alongside
        # the new one and the dashboard reports the two added together.
        dims.activate_period(self.cx, self.period_label)
        # Reference-table sizes are worth reporting too - they show whether a new
        # trim or a new joiner turned up in this workbook.
        for table in ("dim_consultant", "dim_model", "dim_variant", "dim_colour",
                      "dim_lead_source", "dim_team"):
            self.counts[table] = self.one(f"SELECT count(*) FROM {table}")
        return self.counts


def cell_of(ws, row, col):
    return ws.cell(row, col).value


def gcell(grid, row, col):
    """grid[row][col] with ws.cell(row, col).value semantics: out of range is None."""
    if row < 1 or row >= len(grid):
        return None
    r = grid[row]
    return r[col - 1] if 0 < col <= len(r) else None


def gwidth(grid) -> int:
    """The widest row, standing in for ws.max_column."""
    return max((len(r) for r in grid), default=0)


def main():
    ap = argparse.ArgumentParser(description="Load a DSR workbook into Postgres.")
    ap.add_argument("--file", default=str(DEFAULT_FILE))
    ap.add_argument("--dsn", default=DEFAULT_DSN)
    # FIX (2026-10-08): --period used to default to AUG2026 (and --start/--end
    # to August's dates), so anything that ran this without --period - the
    # Drive and email sync daemons do - replaced August with whatever file had
    # just arrived. With no --period the month is now read from the file name
    # ("DSR September 2026.xlsx" -> SEP2026), and a name that does not say
    # which month it is refuses to load rather than guessing.
    ap.add_argument("--period", default=None,
                    help="e.g. SEP2026; read from the file name when omitted")
    ap.add_argument("--start", default=None, help="defaults to the month's first day")
    ap.add_argument("--end", default=None, help="defaults to the month's last day")
    args = ap.parse_args()

    path = Path(args.file)
    if not path.exists():
        raise SystemExit(f"workbook not found: {path}")

    try:
        label, first, last = dims.report_period(args.period, path.name)
    except ValueError as exc:
        raise SystemExit(f"refusing to load {path.name}: {exc}")
    args.period = label
    args.start = args.start or first.isoformat()
    args.end = args.end or last.isoformat()
    print(f"period    {label} ({args.start} to {args.end})")

    print(f"reading   {path.name}")
    # NOT read_only=True. It opens this workbook in 0.8s instead of 22s, but
    # openpyxl reports merged cells differently in that mode: a continuation row
    # on SC Performance comes back carrying the consultant name above it instead
    # of None. load_scorecards() reads that blank as "second channel row for the
    # person above", so every continuation row became a new primary row - 24
    # scorecard rows collapsed to 21, with channels mislabelled. Verified by
    # loading the same workbook both ways and diffing every table.
    wb = openpyxl.load_workbook(path, data_only=True)
    print("finished reading workbook")

    # FIX (2026-10-08): connected without a search_path, but Loader.__init__
    # reads dim_team, dim_consultant... unqualified before run() sets one - so on
    # any database that does not set search_path to dsr itself (a fresh one
    # built from db/schema.sql, for instance) this died with 'relation
    # "dim_team" does not exist'. That broke the README quick start,
    # tools/setup_cloud_db.py and both sync daemons, which all run this. Same
    # option app/db.py gives every pooled connection. (The line below also
    # printed the whole DSN, password included, into the daemons' logs; it now
    # prints only the host part.)
    print(f"connecting to {args.dsn.split('@')[-1]}...")
    with psycopg.connect(args.dsn, connect_timeout=10, prepare_threshold=None,
                         options="-c search_path=dsr,public") as cx:
        print("connected to db!")
        loader = Loader(
            cx, wb, args.period,
            datetime.strptime(args.start, "%Y-%m-%d").date(),
            datetime.strptime(args.end, "%Y-%m-%d").date(),
        )
        counts = loader.run()
        cx.execute("""
            INSERT INTO etl_run (source_file, file_modified, finished_at, row_counts, notes)
            VALUES (%s, %s, now(), %s, %s)
            """, (path.name,
                  datetime.fromtimestamp(path.stat().st_mtime),
                  json.dumps(counts),
                  "; ".join(loader.warnings) or None))
        cx.commit()

    width = max(len(k) for k in counts)
    print("\nloaded:")
    for table, n in counts.items():
        print(f"  {table:<{width}}  {n:>6}")
    if loader.warnings:
        print("\nnotes:")
        for w in loader.warnings:
            print(f"  - {w}")


if __name__ == "__main__":
    main()
