"""
Dimension resolution, shared by the bulk loader and the write API.

Both paths need the same behaviour: given whatever a human typed or a workbook
cell held ("sanjeev", "Walk In", "Taigun (FL)"), find the dimension row it means,
creating it if this is the first time it has been seen. Keeping it in one place is
what stops the API from inventing a second "SANJEEV" beside the loader's.

Every function takes a psycopg connection (or cursor) and returns a surrogate id.
They are safe to call repeatedly - each one is an upsert.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

from . import normalize as nz


def _scalar(cx, sql: str, params: tuple):
    row = cx.execute(sql, params).fetchone()
    if row is None:
        return None
    # The API runs with a dict row factory; the loader does not.
    return next(iter(row.values())) if isinstance(row, dict) else row[0]


def resolve_team(cx, label) -> int | None:
    key = nz.team_key(label)
    if not key:
        return None
    return _scalar(cx,
                   "INSERT INTO dim_team (name) VALUES (%s) "
                   "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
                   "RETURNING team_id", (key,))


def resolve_consultant(cx, label, team=None, channel=None,
                       activate: bool = False) -> int | None:
    """
    Find or create a consultant.

    `activate` marks them as currently on the floor - the write API passes it,
    because anyone being credited with a booking today is working today. The bulk
    loader leaves it false and decides afterwards, so that historical names from
    the 2024 dump do not appear on the current leaderboard.
    """
    key = nz.consultant_key(label)
    if not key:
        return None
    cid = _scalar(cx,
                  "INSERT INTO dim_consultant (full_name, display_name, is_active) "
                  "VALUES (%s, %s, %s) "
                  "ON CONFLICT (full_name) DO UPDATE SET full_name = EXCLUDED.full_name "
                  "RETURNING consultant_id", (key, nz.title(key), activate))
    if activate:
        cx.execute("UPDATE dim_consultant SET is_active = true "
                   "WHERE consultant_id = %s AND NOT is_active", (cid,))
    if team is not None:
        tid = resolve_team(cx, team)
        if tid:
            cx.execute("UPDATE dim_consultant SET team_id = %s WHERE consultant_id = %s "
                       "AND team_id IS DISTINCT FROM %s", (tid, cid, tid))
    if channel is not None:
        cx.execute("UPDATE dim_consultant SET primary_channel = %s "
                   "WHERE consultant_id = %s AND primary_channel IS NULL", (channel, cid))
    return cid


def resolve_model(cx, label) -> int | None:
    key = nz.model_key(label)
    if not key:
        return None
    family, is_cbu = nz.MODEL_MAP.get(key, (key.split()[0], False))
    return _scalar(cx,
                   "INSERT INTO dim_model (name, family, is_cbu) VALUES (%s, %s, %s) "
                   "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
                   "RETURNING model_id", (key, family, is_cbu))


def resolve_variant(cx, model_label, variant_label,
                    long_text=None, model_code=None) -> int | None:
    mid = resolve_model(cx, model_label)
    vkey = nz.variant_key(variant_label)
    if not mid or not vkey:
        return None
    vid = _scalar(cx,
                  "INSERT INTO dim_variant "
                  "  (model_id, name, long_model_text, model_code, transmission) "
                  "VALUES (%s, %s, %s, %s, %s) "
                  "ON CONFLICT (model_id, name) DO UPDATE SET name = EXCLUDED.name "
                  "RETURNING variant_id",
                  (mid, vkey, nz.clean(long_text), nz.upper(model_code),
                   nz.transmission_of(vkey)))
    # The booking tabs name the trim but not the factory text; the stock tabs
    # carry both. Backfill whichever arrives second.
    if long_text or model_code:
        cx.execute("UPDATE dim_variant "
                   "SET long_model_text = COALESCE(long_model_text, %s), "
                   "    model_code = COALESCE(model_code, %s) "
                   "WHERE variant_id = %s",
                   (nz.clean(long_text), nz.upper(model_code), vid))
    return vid


def resolve_colour(cx, label, code=None) -> int | None:
    key = nz.colour_key(label)
    if not key:
        return None
    cid = _scalar(cx,
                  "INSERT INTO dim_colour (name, colour_code) VALUES (%s, %s) "
                  "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
                  "RETURNING colour_id", (key, nz.upper(code)))
    if code:
        cx.execute("UPDATE dim_colour SET colour_code = COALESCE(colour_code, %s) "
                   "WHERE colour_id = %s", (nz.upper(code), cid))
    return cid


def resolve_source(cx, label) -> int | None:
    resolved = nz.source_key(label)
    if not resolved:
        return None
    name, channel, paid = resolved
    return _scalar(cx,
                   "INSERT INTO dim_lead_source (name, channel, is_paid_media) "
                   "VALUES (%s, %s, %s) "
                   "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name "
                   "RETURNING source_id", (name, channel, paid))


_MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
           "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")

_MONTH_WORDS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "september": 9, "oct": 10, "october": 10,
    "nov": 11, "november": 11, "dec": 12, "december": 12,
}


# FIX (2026-10-08): the Drive and email sync daemons always overwrote AUG2026.
# They run `python -m etl.load_dsr --file X` with no --period, and the CLI
# defaulted --period to AUG2026, so every synced workbook - whatever month it
# was for - replaced August. The month-detection rule lived only in the upload
# API (app/entry.py), so the CLI could not use it. It now lives here, the CLI
# and the API both call it, and it refuses to guess instead of defaulting.
def report_period(period: str | None, filename: str) -> tuple[str, date, date]:
    """
    Which month a report is for, from an explicit label or the file name.

    Returns (label, first_day, last_day). Raises ValueError when it cannot tell,
    because guessing a month means replacing whichever month it guessed.
    """
    month = year = None

    # An explicit label is the most reliable signal, and it is the one form the
    # scan below cannot read: in "OCT2026" the year is glued to the month, so
    # there is no word boundary for \b(20\d\d)\b to find.
    tag = re.match(r"^\s*([a-z]{3,9})\s*[-_ ]?\s*(20\d\d)\s*$", (period or "").lower())
    if tag and tag.group(1) in _MONTH_WORDS:
        month, year = _MONTH_WORDS[tag.group(1)], int(tag.group(2))
    else:
        text = f"{period or ''} {filename}".lower()
        for name, num in _MONTH_WORDS.items():
            if re.search(r"\b" + name, text):
                month = num
                break
        ym = re.search(r"\b(20\d\d)\b", text)
        year = int(ym.group(1)) if ym else None

    if month is None or year is None:
        missing = "month" if month is None else "year"
        raise ValueError(
            f"Could not tell which {missing} this report covers, and guessing would "
            f"overwrite whichever month it guessed. Set the period explicitly "
            f"(for example OCT2026), or name the file with its month and year "
            f"(for example 'DSR October 2026.xlsx').")

    # Always the canonical ABBRYYYY. A label typed "OCT 2026" would otherwise
    # create a second period alongside "OCT2026", each holding half the month.
    label = f"{_MONTHS[month - 1]}{year}"
    _, last_day = calendar.monthrange(year, month)
    return label, date(year, month, 1), date(year, month, last_day)


def source_id_by_name(cx, name: str = "DIGITAL") -> int | None:
    """
    The id of a lead source, looked up by its canonical name.

    FIX (2026-10-08): the webhook and /api/crm/leads filed every lead under
    source_id = 1. Surrogate ids are handed out in the order a workbook first
    mentions each source, so id 1 is whichever channel the first load happened
    to meet first - not a fixed meaning, and different on a rebuilt database.
    db/triggers.sql already looks DIGITAL up by name for agent-filed leads; this
    is the same rule for the Python routes. resolve_source() creates the row if
    a fresh database has never seen it.
    """
    return resolve_source(cx, name)


def period_for(cx, on_date: date | None) -> tuple[int, str, bool]:
    """
    Which reporting period a date belongs to.

    Returns (period_id, label, is_active). The period is created if this is the
    first record for that month - a booking dated the 1st of a new month must
    land somewhere, and dropping it on the floor (or forcing it into the month
    the dashboard happens to be showing) would both be wrong.

    `is_active` says whether that period is the one the dashboard is currently
    reporting on, which is what the caller needs in order to tell the user their
    entry was filed under a different month.
    """
    if on_date is None:
        on_date = date.today()

    label = f"{_MONTHS[on_date.month - 1]}{on_date.year}"
    # Calendar month bounds; the DSR is always a monthly report.
    start = on_date.replace(day=1)
    end = (start.replace(year=start.year + 1, month=1) if start.month == 12
           else start.replace(month=start.month + 1)) - timedelta(days=1)

    row = cx.execute("""
        INSERT INTO dim_period (label, period_start, period_end)
        VALUES (%s, %s, %s)
        ON CONFLICT (label) DO UPDATE SET label = EXCLUDED.label
        RETURNING period_id, label, is_active
    """, (label, start, end)).fetchone()
    if isinstance(row, dict):
        return row["period_id"], row["label"], row["is_active"]
    return row[0], row[1], row[2]


def activate_period(cx, label: str) -> dict:
    """
    Make one period the reporting month, and realign the fact tables to it.

    `is_current_period` is stored on each fact row rather than derived, because
    every headline view filters on it and a join through dim_period on every
    query would not pay for itself. The cost is that switching months has to
    rewrite the flag - which is what this does, in one transaction, so the
    dashboard never sees a half-switched state.
    """
    row = cx.execute("SELECT period_id FROM dim_period WHERE upper(label) = upper(%s)",
                     (label,)).fetchone()
    if row is None:
        raise ValueError(f"no period called {label!r}")
    period_id = next(iter(row.values())) if isinstance(row, dict) else row[0]

    # Clear first: the partial unique index allows only one active row.
    cx.execute("UPDATE dim_period SET is_active = false WHERE is_active")
    cx.execute("UPDATE dim_period SET is_active = true WHERE period_id = %s",
               (period_id,))

    print("ACTIVATE PERIOD:", label, "GOT PERIOD_ID:", period_id)
    touched = {}
    for table in ("lead", "booking"):
        print("UPDATING", table, "WITH", period_id)
        touched[table] = cx.execute(
            f"UPDATE {table} SET is_current_period = (COALESCE(period_id, -1) = %s) "
            f"WHERE is_current_period != (COALESCE(period_id, -1) = %s)",
            (period_id, period_id)).rowcount
    return {"period": label, "period_id": period_id, "rows_realigned": touched}
