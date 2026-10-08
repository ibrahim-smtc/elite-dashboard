"""
Report export - the direction the dashboard never had.

Data could always come IN (a DSR workbook uploaded, rows typed on the sheet) and
be read on screen. It could not be got back OUT: a manager who wanted the order
book in Excel had to screenshot a table. This builds the file instead, off the
same views the dashboard draws, so an export and the screen can never disagree.

Two routes:

    GET  /api/export/manifest   what can be exported, with live row counts, so
                                the picker can say "6 sheets, 1,284 rows" before
                                anyone commits to a download
    POST /api/export            build it, and either hand back the file or push
                                it to a cloud destination

Row counts are gathered in ONE statement for the same reason main.py bundles the
dashboard: against this database every query costs a round trip (~370 ms) and
the SQL itself is free, so twelve COUNT(*)s as twelve requests would cost four
seconds to answer a question the user asked by opening a modal.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import fallback
from .db import fetch_all, fetch_one, is_db_ready

log = logging.getLogger("dsr.export")
router = APIRouter(prefix="/api/export", tags=["export"])


# =====================================================================
# What can be exported
# =====================================================================

@dataclass(frozen=True)
class Dataset:
    """
    One worksheet (or one CSV). `sql_current` is the month on screen; `sql_all`
    drops the period filter where that is meaningful. A dataset with no
    `sql_all` is not period-scoped in the first place - stock is stock - and the
    same query answers both.
    """
    key: str
    label: str
    sheet: str
    note: str
    group: str
    sql_current: str
    sql_all: str | None = None
    fallback: Callable[[], Any] | None = None
    # The DSR tab this rebuilds, for the workbook-layout template.
    dsr_sheet: str | None = None


GROUPS: list[dict[str, str]] = [
    {"key": "orders",      "label": "Include Order Book (bookings, customers, fulfilment)"},
    {"key": "enquiries",   "label": "Include Leads & Enquiry Sources"},
    {"key": "stock",       "label": "Include Stock, Ageing & Model Position"},
    {"key": "performance", "label": "Include Consultant Scorecards & Targets"},
]

DATASETS: list[Dataset] = [
    Dataset(
        key="order_book", label="Order book", sheet="Order Book", group="orders",
        note="Every booking with customer, model, consultant and fulfilment state",
        sql_current="SELECT * FROM v_bookings WHERE is_current_period "
                    "ORDER BY booking_date DESC NULLS LAST",
        sql_all="SELECT * FROM v_bookings ORDER BY booking_date DESC NULLS LAST",
        fallback=lambda: fallback.get_bookings(1000),
        dsr_sheet="Current Month Booking",
    ),
    Dataset(
        key="backorders", label="Backorders", sheet="Backorders", group="orders",
        note="Orders with no stock to allot against them, longest wait first",
        sql_current="SELECT * FROM v_backorders WHERE is_current_period "
                    "ORDER BY days_waiting DESC NULLS LAST",
        sql_all="SELECT * FROM v_backorders ORDER BY days_waiting DESC NULLS LAST",
        fallback=fallback.get_backorders,
        dsr_sheet="Pending Booking",
    ),
    Dataset(
        key="commitments", label="Booking commitments", sheet="Commitments", group="orders",
        note="Week-by-week committed bookings against actuals",
        sql_current="SELECT * FROM v_booking_commitments "
                    "ORDER BY consultant_label, window_label",
        fallback=fallback.get_commitments,
        dsr_sheet="Daily Tracker",
    ),
    Dataset(
        key="leads", label="Enquiries", sheet="Enquiries", group="enquiries",
        note="Individual enquiry records with source, model and qualification",
        sql_current="""
            SELECT l.lead_id, l.created_at, l.lead_name, l.mobile, l.email,
                   s.name AS source, s.channel AS source_channel,
                   l.lead_type, l.model_of_interest, l.variant_of_interest,
                   l.colour_of_interest, m.name AS model,
                   c.display_name AS consultant, l.lead_status, l.rating,
                   l.qualified_stage, l.test_drive_given, l.trade_in, l.origin
            FROM lead l
            LEFT JOIN dim_lead_source s ON s.source_id = l.source_id
            LEFT JOIN dim_model       m ON m.model_id  = l.model_id
            LEFT JOIN dim_consultant  c ON c.consultant_id = l.consultant_id
            WHERE l.is_current_period
            ORDER BY l.created_at DESC NULLS LAST
        """,
        sql_all="""
            SELECT l.lead_id, l.created_at, l.lead_name, l.mobile, l.email,
                   s.name AS source, s.channel AS source_channel,
                   l.lead_type, l.model_of_interest, l.variant_of_interest,
                   l.colour_of_interest, m.name AS model,
                   c.display_name AS consultant, l.lead_status, l.rating,
                   l.qualified_stage, l.test_drive_given, l.trade_in, l.origin
            FROM lead l
            LEFT JOIN dim_lead_source s ON s.source_id = l.source_id
            LEFT JOIN dim_model       m ON m.model_id  = l.model_id
            LEFT JOIN dim_consultant  c ON c.consultant_id = l.consultant_id
            ORDER BY l.created_at DESC NULLS LAST
        """,
        dsr_sheet="Leads",
    ),
    Dataset(
        key="lead_sources", label="Enquiries by source", sheet="Source Mix", group="enquiries",
        note="Channel split with qualification rate",
        sql_current="SELECT * FROM v_leads_sourcewise ORDER BY leads DESC",
        fallback=fallback.get_leads_sourcewise,
        dsr_sheet="Source Wise",
    ),
    Dataset(
        key="stock", label="Stock on ground", sheet="Stock", group="stock",
        note="Chassis-level inventory with status and ageing days",
        sql_current="SELECT * FROM v_stock ORDER BY stock_aging_days DESC NULLS LAST",
        dsr_sheet="Free Stock",
    ),
    Dataset(
        key="stock_ageing", label="Stock ageing", sheet="Stock Ageing", group="stock",
        note="Units per ageing bucket, per model",
        sql_current="SELECT * FROM v_stock_ageing ORDER BY model, ageing_bucket",
        fallback=fallback.get_stock_ageing,
        dsr_sheet="Stock Ageing",
    ),
    Dataset(
        key="model_position", label="Model position", sheet="Model Position", group="stock",
        note="Supply against demand for each model family",
        sql_current="SELECT * FROM v_model_position ORDER BY total_stock DESC, model",
        fallback=fallback.get_models_position,
        dsr_sheet="VW Report",
    ),
    Dataset(
        key="leaderboard", label="Consultant leaderboard", sheet="Leaderboard",
        group="performance",
        note="Bookings and retails against target, per consultant",
        sql_current="SELECT * FROM v_consultant_leaderboard",
        fallback=fallback.get_leaderboard,
        dsr_sheet="Daily Tracker",
    ),
    Dataset(
        key="scorecards", label="Full scorecards", sheet="Scorecards", group="performance",
        note="Every scorecard row including channel splits and totals",
        sql_current="SELECT * FROM v_consultant_scorecard",
        fallback=fallback.get_scorecards,
        dsr_sheet="Comparision",
    ),
    Dataset(
        key="funnel_kpi", label="Headline KPI & funnel", sheet="KPI", group="performance",
        note="The figures the top of the dashboard shows",
        sql_current="SELECT * FROM v_daily_kpi",
        fallback=lambda: [fallback.get_kpi()],
    ),
    Dataset(
        key="attachments", label="Attachment rates", sheet="Attachments", group="performance",
        note="Finance, insurance, warranty and SVP mix on retailed cars",
        sql_current="SELECT * FROM v_attachment_rates",
        fallback=lambda: [fallback.get_attachments()],
    ),
]

BY_KEY = {d.key: d for d in DATASETS}

TEMPLATES: list[dict[str, str]] = [
    {"key": "manager", "label": "Manager Summary Workbook",
     "note": "Cover sheet with the month's headline figures, then the data"},
    {"key": "dsr", "label": "DSR Workbook Layout",
     "note": "Sheets named and ordered the way the uploaded DSR names them"},
    {"key": "raw", "label": "Raw Data Tables",
     "note": "One sheet per table, no cover, nothing reformatted"},
]

FORMATS: list[dict[str, str]] = [
    {"key": "xlsx", "label": "Excel Workbook", "ext": ".xlsx",
     "note": "One file, one sheet per table"},
    {"key": "csv", "label": "CSV Files", "ext": ".csv",
     "note": "One CSV per table, zipped when there is more than one"},
]


# =====================================================================
# Cloud destinations
# =====================================================================

_SERVICE_ACCOUNT = Path(__file__).resolve().parent.parent / os.environ.get(
    "GOOGLE_SERVICE_ACCOUNT_FILE", "nodal-operand-434003-p2-3769c8bfc8a7.json")
# Deliberately its own setting, and deliberately not defaulted to the folder
# etl/drive_sync.py watches: that folder is the INBOUND one, polled for new DSR
# workbooks to ingest, so an export written there would be picked up and loaded
# back in as though it were a new report. Without an explicit export folder the
# upload would also land in the service account's own Drive, where nobody at the
# dealership can see it - so Drive is reported as not connected until this is
# set, rather than silently posting files into a hole.
_DRIVE_FOLDER = os.environ.get("GOOGLE_DRIVE_EXPORT_FOLDER_ID", "")


def _destinations() -> list[dict[str, Any]]:
    """
    Which destinations are actually wired up.

    Reported honestly rather than drawn as four equal buttons: Drive is offered
    only if the service-account key is really on disk, and Dropbox and OneDrive
    say they are not connected, naming the setting that would connect them,
    instead of being offered and then failing at the last click.
    """
    has_key = _SERVICE_ACCOUNT.exists()
    drive_ready = has_key and bool(_DRIVE_FOLDER)
    dropbox_ready = bool(os.environ.get("DROPBOX_ACCESS_TOKEN"))
    onedrive_ready = bool(os.environ.get("ONEDRIVE_ACCESS_TOKEN"))
    return [
        {"key": "local", "label": "Local PC", "status": "ready",
         "note": "Downloads straight to this computer", "requires": None},
        {"key": "google_drive", "label": "Google Drive",
         "status": "ready" if drive_ready else "not_configured",
         "note": ("Uploads into the dealership's export folder" if drive_ready
                  else "Name an export folder to connect this" if has_key
                  else "Add the service-account key to connect this"),
         "requires": None if drive_ready else (
             "GOOGLE_DRIVE_EXPORT_FOLDER_ID" if has_key else "GOOGLE_SERVICE_ACCOUNT_FILE")},
        {"key": "dropbox", "label": "Dropbox",
         "status": "ready" if dropbox_ready else "not_configured",
         "note": "Connected" if dropbox_ready else "Not connected yet",
         "requires": None if dropbox_ready else "DROPBOX_ACCESS_TOKEN"},
        {"key": "onedrive", "label": "OneDrive",
         "status": "ready" if onedrive_ready else "not_configured",
         "note": "Connected" if onedrive_ready else "Not connected yet",
         "requires": None if onedrive_ready else "ONEDRIVE_ACCESS_TOKEN"},
    ]


def _push_to_drive(blob: bytes, filename: str, mime: str) -> dict[str, Any]:
    """Upload a finished export into the shared Drive folder."""
    if not _SERVICE_ACCOUNT.exists():
        raise HTTPException(400, "Google Drive is not connected on this server.")
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseUpload
    except ImportError as exc:
        raise HTTPException(500, f"Google Drive libraries are not installed: {exc}")

    try:
        creds = service_account.Credentials.from_service_account_file(
            str(_SERVICE_ACCOUNT), scopes=["https://www.googleapis.com/auth/drive.file"])
        svc = build("drive", "v3", credentials=creds)
        meta: dict[str, Any] = {"name": filename}
        if _DRIVE_FOLDER:
            meta["parents"] = [_DRIVE_FOLDER]
        created = svc.files().create(
            body=meta,
            media_body=MediaIoBaseUpload(io.BytesIO(blob), mimetype=mime, resumable=False),
            fields="id, name, webViewLink",
        ).execute()
        return {"id": created.get("id"), "name": created.get("name"),
                "link": created.get("webViewLink")}
    except HTTPException:
        raise
    except Exception as exc:
        # The service account may hold read-only rights on that folder, which is
        # a configuration fact worth saying out loud rather than a bare 500.
        raise HTTPException(502, f"Google Drive rejected the upload: {exc}")


# =====================================================================
# Reading the rows
# =====================================================================

def _rows(ds: Dataset, scope: str) -> list[dict[str, Any]]:
    sql = (ds.sql_all or ds.sql_current) if scope == "all" else ds.sql_current
    if is_db_ready():
        try:
            return fetch_all(sql) or []
        except Exception as exc:
            log.warning("export: %s failed (%s), falling back", ds.key, exc)
    if ds.fallback:
        try:
            got = ds.fallback()
            return list(got) if isinstance(got, list) else [got]
        except Exception:
            return []
    return []


# Counts for every dataset in one statement, for the reason given at the top.
_COUNT_BUNDLE_CURRENT = """
SELECT json_build_object(
  'order_book',     (SELECT count(*) FROM v_bookings WHERE is_current_period),
  'backorders',     (SELECT count(*) FROM v_backorders WHERE is_current_period),
  'commitments',    (SELECT count(*) FROM v_booking_commitments),
  'leads',          (SELECT count(*) FROM lead WHERE is_current_period),
  'lead_sources',   (SELECT count(*) FROM v_leads_sourcewise),
  'stock',          (SELECT count(*) FROM v_stock),
  'stock_ageing',   (SELECT count(*) FROM v_stock_ageing),
  'model_position', (SELECT count(*) FROM v_model_position),
  'leaderboard',    (SELECT count(*) FROM v_consultant_leaderboard),
  'scorecards',     (SELECT count(*) FROM v_consultant_scorecard),
  'funnel_kpi',     (SELECT count(*) FROM v_daily_kpi),
  'attachments',    (SELECT count(*) FROM v_attachment_rates)
) AS counts
"""

_COUNT_BUNDLE_ALL = """
SELECT json_build_object(
  'order_book',     (SELECT count(*) FROM v_bookings),
  'backorders',     (SELECT count(*) FROM v_backorders),
  'commitments',    (SELECT count(*) FROM v_booking_commitments),
  'leads',          (SELECT count(*) FROM lead),
  'lead_sources',   (SELECT count(*) FROM v_leads_sourcewise),
  'stock',          (SELECT count(*) FROM v_stock),
  'stock_ageing',   (SELECT count(*) FROM v_stock_ageing),
  'model_position', (SELECT count(*) FROM v_model_position),
  'leaderboard',    (SELECT count(*) FROM v_consultant_leaderboard),
  'scorecards',     (SELECT count(*) FROM v_consultant_scorecard),
  'funnel_kpi',     (SELECT count(*) FROM v_daily_kpi),
  'attachments',    (SELECT count(*) FROM v_attachment_rates)
) AS counts
"""


def _counts(scope: str) -> dict[str, int]:
    if is_db_ready():
        try:
            row = fetch_one(_COUNT_BUNDLE_ALL if scope == "all" else _COUNT_BUNDLE_CURRENT)
            if row and row.get("counts"):
                got = row["counts"]
                if isinstance(got, str):
                    got = json.loads(got)
                return {k: int(v or 0) for k, v in got.items()}
        except Exception as exc:
            log.warning("export: count bundle failed (%s)", exc)
    # No database: count what the snapshot can actually produce, so the picker
    # still shows real numbers rather than an optimistic guess.
    return {d.key: (len(_rows(d, scope)) if d.fallback else 0) for d in DATASETS}


def _active_period() -> dict[str, Any]:
    if is_db_ready():
        try:
            row = fetch_one("SELECT label, period_start, period_end "
                            "FROM dim_period WHERE is_active LIMIT 1")
            if row:
                return {"label": row["label"],
                        "period_start": str(row["period_start"]),
                        "period_end": str(row["period_end"])}
        except Exception:
            pass
    periods = fallback.get_periods() or []
    act = next((p for p in periods if p.get("is_active")), periods[0] if periods else {})
    return {"label": act.get("label", "CURRENT"),
            "period_start": act.get("period_start"),
            "period_end": act.get("period_end")}


# =====================================================================
# Building the file
# =====================================================================

def _clean(v: Any) -> Any:
    """Excel and CSV both want plain scalars; psycopg hands back rather more."""
    if v is None or isinstance(v, (str, int, float, bool, datetime, date)):
        return v
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return str(v)


def _header(name: str) -> str:
    """`booking_amount` reads as a column name; `Booking Amount` reads as a heading."""
    return name.replace("_", " ").strip().title()


def _sheet_name(ds: Dataset, template: str) -> str:
    name = ds.dsr_sheet if (template == "dsr" and ds.dsr_sheet) else ds.sheet
    # Excel's own limits: 31 characters, and none of : \ / ? * [ ]
    for ch in ":\\/?*[]":
        name = name.replace(ch, "-")
    return name[:31] or ds.key[:31]


def _unique(name: str, taken: set[str]) -> str:
    """
    Two datasets can legitimately want one name - under the DSR layout both the
    leaderboard and the commitments rebuild "Daily Tracker" - and openpyxl will
    happily create the duplicate that Excel then refuses to open.
    """
    if name not in taken:
        taken.add(name)
        return name
    for n in range(2, 60):
        candidate = f"{name[:31 - len(str(n)) - 1]} {n}"
        if candidate not in taken:
            taken.add(candidate)
            return candidate
    taken.add(name)
    return name


def _build_xlsx(selected: list[Dataset], scope: str, template: str,
                meta: dict[str, Any]) -> tuple[bytes, dict[str, int]]:
    import openpyxl
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.utils import get_column_letter

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    head_fill = PatternFill("solid", fgColor="1F3864")
    head_font = Font(bold=True, color="FFFFFF", size=10)
    title_font = Font(bold=True, size=14, color="1F3864")
    thin = Side(style="thin", color="D9D9D9")
    edge = Border(bottom=thin)

    written: dict[str, int] = {}
    per_sheet: list[tuple[str, str, int]] = []
    taken: set[str] = set()

    # The cover goes in first so it is the sheet the workbook opens on, but its
    # numbers are only known once the data is written - so it is created here
    # and filled at the end.
    cover = wb.create_sheet("Summary") if template == "manager" else None
    if cover is not None:
        taken.add("Summary")

    for ds in selected:
        rows = _rows(ds, scope)
        ws = wb.create_sheet(_unique(_sheet_name(ds, template), taken))
        written[ds.key] = len(rows)
        per_sheet.append((ws.title, ds.label, len(rows)))

        if not rows:
            ws["A1"] = f"{ds.label} - no rows for this selection"
            ws["A1"].font = Font(italic=True, color="808080")
            continue

        cols = list(rows[0].keys())
        for i, col in enumerate(cols, start=1):
            cell = ws.cell(row=1, column=i, value=_header(col))
            cell.fill, cell.font = head_fill, head_font
            cell.alignment = Alignment(vertical="center", wrap_text=False)

        for r, row in enumerate(rows, start=2):
            for c, col in enumerate(cols, start=1):
                raw = row.get(col)
                cell = ws.cell(row=r, column=c, value=_clean(raw))
                cell.border = edge
                if isinstance(raw, datetime):
                    cell.number_format = "DD-MMM-YYYY HH:MM"
                elif isinstance(raw, date):
                    cell.number_format = "DD-MMM-YYYY"

        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(cols))}{len(rows) + 1}"
        for i, col in enumerate(cols, start=1):
            longest = max([len(_header(col))]
                          + [len(str(_clean(r.get(col)) or "")) for r in rows[:200]])
            ws.column_dimensions[get_column_letter(i)].width = min(max(longest + 2, 10), 42)

    if cover is not None:
        cover["A1"] = "Volkswagen Elite Motors - DSR Export"
        cover["A1"].font = title_font
        info = [
            ("Reporting month", meta.get("period")),
            ("Scope", "Active month only" if scope == "current" else "Every month on record"),
            ("Template", next((t["label"] for t in TEMPLATES if t["key"] == template), template)),
            ("Generated", meta.get("generated_at")),
            ("Source", "Live database" if is_db_ready() else "Offline snapshot"),
        ]
        r = 3
        for label, value in info:
            cover.cell(row=r, column=1, value=label).font = Font(bold=True, size=10)
            cover.cell(row=r, column=2, value=value)
            r += 1

        r += 1
        for c, title in enumerate(("Sheet", "Contents", "Rows"), start=1):
            cell = cover.cell(row=r, column=c, value=title)
            cell.fill, cell.font = head_fill, head_font
        for sheet, label, n in per_sheet:
            r += 1
            cover.cell(row=r, column=1, value=sheet)
            cover.cell(row=r, column=2, value=label)
            cover.cell(row=r, column=3, value=n)
        cover.column_dimensions["A"].width = 26
        cover.column_dimensions["B"].width = 52
        cover.column_dimensions["C"].width = 10

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue(), written


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    buf = io.StringIO(newline="")
    if rows:
        cols = list(rows[0].keys())
        w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
        w.writerow({c: _header(c) for c in cols})
        for row in rows:
            w.writerow({c: _clean(row.get(c)) for c in cols})
    # utf-8-sig, so Excel on Windows opens the file with the rupee sign and
    # customer names intact rather than as mojibake.
    return buf.getvalue().encode("utf-8-sig")


def _build_csv(selected: list[Dataset], scope: str, template: str,
               stem: str) -> tuple[bytes, dict[str, int], str, str]:
    written: dict[str, int] = {}
    parts: list[tuple[str, bytes]] = []
    taken: set[str] = set()
    for ds in selected:
        rows = _rows(ds, scope)
        written[ds.key] = len(rows)
        name = _unique(_sheet_name(ds, template), taken).replace(" ", "_")
        parts.append((f"{name}.csv", _csv_bytes(rows)))

    if len(parts) == 1:
        return parts[0][1], written, "text/csv", ".csv"

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in parts:
            z.writestr(f"{stem}/{name}", blob)
    return buf.getvalue(), written, "application/zip", ".zip"


# =====================================================================
# Routes
# =====================================================================

class ExportRequest(BaseModel):
    format: str = Field("xlsx", description="xlsx or csv")
    scope: str = Field("current", description="current (active month) or all")
    template: str = Field("manager", description="manager, dsr or raw")
    groups: list[str] = Field(default_factory=list, description="Source groups to include")
    datasets: list[str] = Field(default_factory=list,
                                description="Explicit dataset keys; overrides groups")
    destination: str = Field("local",
                             description="local, google_drive, dropbox or onedrive")
    filename: str | None = None


@router.get("/manifest")
def export_manifest(scope: str = "current"):
    """
    Everything the export picker needs to draw itself, in one request: the
    datasets, their live row counts, the templates and formats, which
    destinations are actually connected, and the month being exported.
    """
    scope = "all" if scope == "all" else "current"
    counts = _counts(scope)
    return {
        "scope": scope,
        "period": _active_period(),
        "source": "database" if is_db_ready() else "snapshot",
        "groups": [
            {**g,
             "datasets": [d.key for d in DATASETS if d.group == g["key"]],
             "rows": sum(counts.get(d.key, 0) for d in DATASETS if d.group == g["key"])}
            for g in GROUPS
        ],
        "datasets": [
            {"key": d.key, "label": d.label, "sheet": d.sheet, "note": d.note,
             "group": d.group, "rows": counts.get(d.key, 0)}
            for d in DATASETS
        ],
        "templates": TEMPLATES,
        "formats": FORMATS,
        "destinations": _destinations(),
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


@router.post("")
def run_export(req: ExportRequest):
    """
    Build the file. A local destination gets the bytes back directly; a cloud
    destination gets JSON naming where the file landed.
    """
    fmt = req.format if req.format in {f["key"] for f in FORMATS} else "xlsx"
    scope = "all" if req.scope == "all" else "current"
    template = req.template if req.template in {t["key"] for t in TEMPLATES} else "manager"

    if req.datasets:
        keys = {k for k in req.datasets if k in BY_KEY}
    else:
        wanted = set(req.groups) or {g["key"] for g in GROUPS}
        keys = {d.key for d in DATASETS if d.group in wanted}
    if not keys:
        raise HTTPException(400, "Choose at least one thing to export.")

    # Registry order, not click order, so two exports of the same selection are
    # byte-for-byte the same workbook layout.
    selected = [d for d in DATASETS if d.key in keys]

    # Refused before the workbook is built rather than after: there is no point
    # spending a Drive-sized export on a destination that cannot receive it.
    if req.destination != "local":
        dest = next((d for d in _destinations() if d["key"] == req.destination), None)
        if not dest or dest["status"] != "ready":
            label = dest["label"] if dest else req.destination
            needs = (dest or {}).get("requires") or "an access token"
            raise HTTPException(
                400,
                f"{label} is not connected on this server. Download to this "
                f"computer instead, or set {needs}.")

    period = _active_period()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    stem = (req.filename or "").strip() or (
        f"VW-Elite-DSR-{period.get('label') or 'export'}"
        f"{'' if scope == 'current' else '-all-months'}-{stamp}")
    stem = "".join(ch for ch in stem if ch.isalnum() or ch in "-_ .").strip() or "dsr-export"

    meta = {"period": period.get("label"),
            "generated_at": datetime.now().strftime("%d %b %Y, %H:%M")}

    if fmt == "xlsx":
        blob, written = _build_xlsx(selected, scope, template, meta)
        mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ext = ".xlsx"
    else:
        blob, written, mime, ext = _build_csv(selected, scope, template, stem)

    filename = f"{stem}{ext}"
    total = sum(written.values())

    if req.destination == "google_drive":
        uploaded = _push_to_drive(blob, filename, mime)
        return {
            "status": "success", "destination": "google_drive", "filename": filename,
            "bytes": len(blob), "rows": total, "sheets": len(selected),
            "counts": written, "period": period.get("label"), "scope": scope,
            "drive": uploaded,
            "message": f"{filename} uploaded to Google Drive ({total:,} rows).",
        }

    return StreamingResponse(
        io.BytesIO(blob),
        media_type=mime,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(blob)),
            # A blob download tells the browser nothing about what it contains,
            # and the modal wants to report what it just produced.
            "X-Export-Rows": str(total),
            "X-Export-Sheets": str(len(selected)),
            "X-Export-Filename": filename,
            "Access-Control-Expose-Headers":
                "Content-Disposition, X-Export-Rows, X-Export-Sheets, X-Export-Filename",
        },
    )
