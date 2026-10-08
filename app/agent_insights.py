"""
Month-aware figures for the dashboard's AI agent (app/mcp_server.py).

The dashboard reports one month at a time: whichever month someone last picked
in its month selector becomes the active month for everybody (POST
/api/period/{label}/activate), and every dashboard view counts that month. An
agent answering "how many bookings this month?" from those views therefore
answered for whatever month was picked - August, while the calendar said
October.

These read any month the agent names, and default to the calendar month.
They count the way the views do - a row belongs to the month it is filed
under (period_id), which for the active month is exactly the dashboard's
is_current_period - so for the month on screen the figures match the
dashboard, and for any other month they are what the dashboard would show
with that month picked. Totals are counted here: a model asked to count fifty
rows gets it wrong.
"""
from __future__ import annotations

import calendar
import re
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException

from .db import session

_IST = timezone(timedelta(hours=5, minutes=30))

_MONTH_NUMBERS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
_MONTH_NUMBERS.update({name.lower(): i for i, name in enumerate(calendar.month_abbr) if name})
_MONTH_NUMBERS["sept"] = 9


def _today() -> date:
    return datetime.now(_IST).date()


def _label(d: date) -> str:
    return f"{calendar.month_abbr[d.month].upper()}{d.year}"


def resolve_month(text: str | None) -> dict:
    """A month as the agent names it: 'current' (default: the calendar month),
    'active' (the month the dashboard is set to), 'last', 'September',
    'sep 2026', 'SEP2026' or '2026-09'. A month named without a year is the
    latest one not after this month."""
    today = _today()
    raw = (text or "current").strip()
    t = raw.lower().replace("_", " ").strip()
    with session() as cx:
        periods = cx.execute(
            "SELECT period_id, label, period_start, period_end, is_active FROM dim_period").fetchall()
    active = next((p for p in periods if p["is_active"]), None)

    if t in ("active", "reporting", "dashboard", "selected", "reporting month"):
        if not active:
            raise HTTPException(400, "No month is active on the dashboard.")
        day = active["period_start"]
    elif t in ("current", "this month", "this", "now", "today", "calendar", "calendar month"):
        day = today
    elif t in ("last", "last month", "previous", "previous month"):
        day = today.replace(day=1) - timedelta(days=1)
    elif t in ("next", "next month", "coming month"):
        day = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
    else:
        day = _parse_month(t, today)
        if day is None:
            raise HTTPException(400, f"Not a month: {raw!r}. Use current, last, a month name such as "
                                     "September, or a label such as SEP2026.")

    period = next((p for p in periods if p["period_start"] <= day <= p["period_end"]), None)
    first = day.replace(day=1)
    last = first.replace(day=calendar.monthrange(first.year, first.month)[1])
    return {
        "period_id": period["period_id"] if period else None,
        "month": period["label"] if period else _label(first),
        "from": (period["period_start"] if period else first).isoformat(),
        "to": (period["period_end"] if period else last).isoformat(),
        "calendar_month": _label(today),
        "dashboard_month": active["label"] if active else None,
    }


def _parse_month(t: str, today: date) -> date | None:
    t = t.replace(",", " ")
    # 2026-09
    parts = t.split("-")
    if len(parts) == 2 and all(p.isdigit() for p in parts) and len(parts[0]) == 4:
        y, m = int(parts[0]), int(parts[1])
        return date(y, m, 1) if 1 <= m <= 12 else None
    # SEP2026, sep 2026, september 2026, september
    letters = "".join(ch for ch in t if ch.isalpha())
    digits = "".join(ch for ch in t if ch.isdigit())
    m = _MONTH_NUMBERS.get(letters)
    if not m:
        return None
    if len(digits) == 4:
        return date(int(digits), m, 1)
    if digits:
        return None
    y = today.year if m <= today.month else today.year - 1
    return date(y, m, 1)


def _scope(month: str | None, date_from: str | None, date_to: str | None, date_col: str,
           alias: str) -> tuple[str, list, dict]:
    """The WHERE for a month (by the month a row is filed under) or for a span
    of days (on `date_col`). Days, when given, win."""
    from .crm_api import _date_clause, span     # one reading of days and spans for every tool
    if not (date_from or date_to) and span(month):   # "this week" passed as a month
        date_from = date_to = month
    dated = _date_clause(f"{date_col}::date", date_from, date_to)
    if dated:
        lo, hi = dated[1]
        about = {"from": lo.isoformat(), "to": hi.isoformat(), "calendar_month": _label(_today())}
        return f"{date_col}::date BETWEEN %s AND %s", [lo, hi], about
    m = resolve_month(month)
    if m["period_id"] is None:
        return "FALSE", [], {**m, "note": f"Nothing has been filed under {m['month']} yet."}
    return f"{alias}.period_id = %s", [m["period_id"]], m


def _note(about: dict) -> dict:
    """Say plainly which month a figure is for, when the dashboard is set to another."""
    month, shown = about.get("month"), about.get("dashboard_month")
    if month and shown and month != shown and "note" not in about:
        about = {**about, "note": f"These figures are for {month}. The dashboard is currently set to "
                                  f"{shown}, so its screens show {shown}."}
    return about


def when(about: dict) -> str:
    """The period of a figure in words: "September 2026", "8 Oct 2026",
    "5 Oct - 11 Oct 2026"."""
    if about.get("month") and "period_id" in about:
        try:
            return datetime.strptime(about["month"], "%b%Y").strftime("%B %Y")
        except ValueError:
            return about["month"]
    lo, hi = date.fromisoformat(about["from"]), date.fromisoformat(about["to"])
    if lo == hi:
        return f"{lo.day} {lo:%b %Y}"
    return f"{lo.day} {lo:%b} - {hi.day} {hi:%b %Y}"


def _listing(counts: dict[str, int], n: int = 8) -> str:
    items = [f"{k} {v}" for k, v in counts.items() if k not in ("Not recorded", "Not assigned")][:n]
    return ", ".join(items)


def _tally(rows: list[dict], key: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for r in rows:
        k = r[key] or "Not recorded"
        out[k] = out.get(k, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: (-kv[1], kv[0])))


def _against(n, target, what: str = "") -> str:
    """'17 retails (target 52)', or with no target when the month has none."""
    return f"{n}{' ' + what if what else ''}" + (f" (target {target})" if target is not None else "")


def _grand_total(cx, period_id) -> dict:
    """The dealership's line on a month's scorecard: its TOTAL row, read as the
    People page reads a consultant's (targets from the primary-channel row,
    achievement summed) - or, for a workbook with no TOTAL row, its team rows
    added up, which is what the TOTAL row is. A test workbook holding one team
    and no TOTAL row left September with no targets and no test drives. n is 0
    when the month has neither."""
    for kind in ("GRAND_TOTAL", "TEAM_TOTAL"):
        g = cx.execute("""
            SELECT sum(enquiry_target) AS enquiry_target, sum(test_drive_target) AS test_drive_target,
                   sum(booking_target) AS booking_target, sum(retail_target)     AS retail_target,
                   sum(test_drives)    AS test_drives,    count(*)               AS n
              FROM (SELECT max(leads_target)   FILTER (WHERE is_primary_channel) AS enquiry_target,
                           max(td_target)      FILTER (WHERE is_primary_channel) AS test_drive_target,
                           max(booking_target) FILTER (WHERE is_primary_channel) AS booking_target,
                           max(retail_target)  FILTER (WHERE is_primary_channel) AS retail_target,
                           sum(td_achieved)                                      AS test_drives
                      FROM target_consultant_scorecard
                     WHERE period_id = %s AND row_kind = %s
                     GROUP BY row_label) line""", (period_id, kind)).fetchone()
        if g["n"]:
            break
    return g


def _month_retails(cx, m: dict, consultant_id: int | None = None) -> int:
    """A month's retails (see _RETAILED_IN_MONTH): the dealership's, or one consultant's."""
    mine = " AND rg.consultant_id = %(c)s" if consultant_id is not None else ""
    return cx.execute(f"SELECT count(*) AS n FROM registration rg WHERE {_RETAILED_IN_MONTH}{mine}",
                      {"p": m["period_id"], "lo": m["from"], "hi": m["to"], "c": consultant_id}).fetchone()["n"]


_RETAILS_NOTE = ("retails: cars registered in the month, as the DSR scorecard and the dashboard's headline "
                 "count them. by_status is where each of the month's bookings stands now - its RETAILED "
                 "count is not the month's retails.")


def bookings_summary(month: str | None = None, date_from: str | None = None,
                     date_to: str | None = None) -> dict:
    """Bookings counted for a month or a span of days: the total, and by model
    (family, as the Inventory page counts them), by model as recorded, by
    consultant and by fulfilment status."""
    where, params, about = _scope(month, date_from, date_to, "b.booking_date", "b")
    with session() as cx:
        rows = cx.execute(f"""
            SELECT coalesce(m.family, 'Not recorded') AS family, coalesce(m.name, 'Not recorded') AS model,
                   coalesce(c.display_name, 'Not assigned') AS consultant,
                   coalesce(b.fulfilment_status::text, 'Not recorded') AS status
              FROM booking b
              LEFT JOIN dim_model m      ON m.model_id      = b.model_id
              LEFT JOIN dim_consultant c ON c.consultant_id = b.consultant_id
             WHERE {where}""", params).fetchall()
    out = {**_note(about), "total": len(rows),
           "by_model": _tally(rows, "family"), "by_model_as_recorded": _tally(rows, "model"),
           "by_consultant": _tally(rows, "consultant"), "by_status": _tally(rows, "status")}
    out["answer"] = (f"{when(about)}: {len(rows)} booking{'s' if len(rows) != 1 else ''}"
                     + (f" - by model: {_listing(out['by_model'])}." if rows else "."))
    if about.get("period_id"):
        # The month's retails beside its bookings. Asked for September's
        # retails, the agent gave the bookings since retailed, from by_status
        # (12); the month's retails - cars registered - are 17.
        with session() as cx:
            out["retails"] = _month_retails(cx, about)
            out["retail_target"] = _num(_grand_total(cx, about["period_id"])["retail_target"])
        out["retails_note"] = _RETAILS_NOTE
        out["answer"] += (f" Retails (cars registered) in {when(about)}: "
                          f"{_against(out['retails'], out['retail_target'])}.")
    return out


def leads_summary(month: str | None = None, date_from: str | None = None,
                  date_to: str | None = None) -> dict:
    """Enquiries counted for a month or a span of days: the total and how many
    qualified, by source channel (CRM, walk-in, tele...), by model and by
    consultant."""
    where, params, about = _scope(month, date_from, date_to, "l.created_at", "l")
    with session() as cx:
        rows = cx.execute(f"""
            SELECT coalesce(s.channel::text, 'Not recorded') AS source,
                   coalesce(m.family, 'Not recorded') AS model,
                   coalesce(c.display_name, 'Not assigned') AS consultant,
                   l.qualified_stage = 'Qualified' AS qualified
              FROM lead l
              LEFT JOIN dim_lead_source s ON s.source_id     = l.source_id
              LEFT JOIN dim_model m       ON m.model_id      = l.model_id
              LEFT JOIN dim_consultant c  ON c.consultant_id = l.consultant_id
             WHERE {where}""", params).fetchall()
    out = {**_note(about), "total": len(rows), "qualified": sum(1 for r in rows if r["qualified"]),
           "by_source": _tally(rows, "source"), "by_model": _tally(rows, "model"),
           "by_consultant": _tally(rows, "consultant")}
    if about.get("period_id"):
        # By consultant as the scorecard and the People page count them. Leads
        # from the CRM export carry no consultant: counted from the leads, 270
        # of September's 271 had none, and Sanjeev had 0 - his scorecard says 27.
        with session() as cx:
            got = cx.execute(f"SELECT c.display_name AS name, {_ENQUIRIES_IN_MONTH} AS n FROM dim_consultant c",
                             {"p": about["period_id"]}).fetchall()
        out["by_consultant"] = dict(sorted(((r["name"], int(r["n"])) for r in got if r["n"]),
                                           key=lambda kv: (-kv[1], kv[0])))
        out["by_consultant_note"] = ("A consultant's enquiries as the scorecard and the People page count "
                                     "them: the month's workbook figure plus enquiries entered since. Leads "
                                     "from the CRM export carry no consultant, so these need not add up to "
                                     "the total.")
    out["answer"] = (f"{when(about)}: {len(rows)} enquir{'ies' if len(rows) != 1 else 'y'}, "
                     f"{out['qualified']} qualified"
                     + (f" - by source: {_listing(out['by_source'])}." if rows else "."))
    return out


# A consultant's enquiries for a month as the scorecard counts them: the
# workbook's figure plus enquiries entered since. Leads loaded from the CRM
# export carry no consultant, so counting leads alone found almost none.
_ENQUIRIES_IN_MONTH = """(coalesce((SELECT sum(sc.total_leads) FROM target_consultant_scorecard sc
                  WHERE sc.consultant_id = c.consultant_id AND sc.period_id = %(p)s
                    AND sc.row_kind = 'CONSULTANT'), 0)
       + (SELECT count(*) FROM lead l
           WHERE l.consultant_id = c.consultant_id AND l.period_id = %(p)s
             AND l.origin = 'MANUAL'))"""

# A month's retails: the registrations its workbook listed - each workbook's
# registration tab is that month's retails, and its scorecard counts exactly
# those rows - plus any entered by hand during the month. As the dashboard
# counts them (db/views.sql); counted over every load, August and September
# ran together and Sanjeev had 7 August retails against the workbook's 4.
_RETAILED_IN_MONTH = """rg.status = 'REGISTERED'
       AND (rg.load_period_id = %(p)s
            OR (rg.load_period_id IS NULL
                AND (rg.loaded_at AT TIME ZONE 'Asia/Kolkata')::date BETWEEN %(lo)s AND %(hi)s))"""


def consultant_leaderboard(month: str | None = None, top: int = 10) -> dict:
    """Consultants ranked as the People page ranks them - by bookings, then
    retails - for any month, with their booking target where the month's
    workbook set one."""
    m = resolve_month(month)
    about = _note(m)
    if m["period_id"] is None:
        return {**about, "consultants": [], "note": f"Nothing has been filed under {m['month']} yet.",
                "answer": f"No bookings recorded for {when(m)}."}
    with session() as cx:
        rows = cx.execute(f"""
            SELECT c.display_name AS consultant, t.name AS team,
                   (SELECT count(*) FROM booking b
                     WHERE b.consultant_id = c.consultant_id AND b.period_id = %(p)s) AS bookings,
                   {_ENQUIRIES_IN_MONTH} AS enquiries,
                   (SELECT max(sc.booking_target) FROM target_consultant_scorecard sc
                     WHERE sc.consultant_id = c.consultant_id AND sc.period_id = %(p)s
                       AND sc.is_primary_channel) AS booking_target,
                   -- The People page breaks a tie on bookings by retails.
                   (SELECT count(*) FROM registration rg
                     WHERE rg.consultant_id = c.consultant_id
                       AND {_RETAILED_IN_MONTH}) AS retails
              FROM dim_consultant c
              LEFT JOIN dim_team t ON t.team_id = c.team_id
             WHERE c.is_active""", {"p": m["period_id"], "lo": m["from"], "hi": m["to"]}).fetchall()
    board = []
    for r in rows:
        if not (r["bookings"] or r["enquiries"] or r["booking_target"]):
            continue
        target = int(r["booking_target"]) if r["booking_target"] is not None else None
        entry = {"consultant": r["consultant"], "team": r["team"], "bookings": r["bookings"],
                 "booking_target": target,
                 "pct_of_target": round(100 * r["bookings"] / target) if target else None,
                 "enquiries": int(r["enquiries"] or 0), "retails": int(r["retails"] or 0)}
        board.append(entry)
    # The page's order: bookings, then retails, then - as its rows arrive from
    # v_consultant_leaderboard - furthest behind booking target first.
    board.sort(key=lambda e: (-e["bookings"], -e["retails"],
                              e["bookings"] - (e["booking_target"] or 0), e["consultant"]))
    for i, e in enumerate(board, 1):
        e["rank"] = i
    top = max(1, min(int(top or 10), 50))
    shown = board[:top]
    answer = (f"Top {len(shown)} consultant{'s' if len(shown) != 1 else ''} by bookings, {when(m)}: "
              + "; ".join(f"{e['rank']}. {e['consultant']} - {e['bookings']}" for e in shown) + "."
              if shown and shown[0]["bookings"] else f"No bookings recorded for {when(m)}.")
    return {**about, "total_bookings": sum(e["bookings"] for e in board),
            "consultants_ranked": len(board), "consultants": shown, "answer": answer}


# ------------------------------------------------------------ rankings
#
# "Top 5 bookings", "top 10 consultants", "which model sells most": a chat
# model given lists answers these by taking the first rows - the newest - and
# calling them the top. Every ranking is made here, ranked and counted, with
# the sentence that answers it.

_TOP = {
    "consultants": ("bookings", "enquiries", "test_drives", "retails"),
    "models": ("bookings", "enquiries", "free_stock", "backorders"),
    "sources": ("enquiries", "qualified"),
    "bookings": ("amount",),
    "stock": ("age",),
    "test_drive_cars": ("test_drives",),
    "test_drive_executives": ("test_drives",),
}
_WHAT = {
    "consultant": "consultants", "executive": "consultants", "executives": "consultants",
    "sales executives": "consultants", "salespeople": "consultants", "team": "consultants", "people": "consultants",
    "model": "models", "car": "models", "cars": "models", "vehicles": "models",
    "source": "sources", "lead sources": "sources", "channel": "sources", "channels": "sources",
    "booking": "bookings", "order": "bookings", "orders": "bookings", "deals": "bookings",
    "inventory": "stock", "oldest stock": "stock", "ageing": "stock", "aging": "stock", "ageing stock": "stock",
    "test drive cars": "test_drive_cars", "test drives by car": "test_drive_cars",
    "test drive executives": "test_drive_executives", "test drives by executive": "test_drive_executives",
}
_BY = {
    "booking": "bookings", "sales": "bookings", "enquiry": "enquiries", "leads": "enquiries", "lead": "enquiries",
    "stock": "free_stock", "free stock": "free_stock", "backorder": "backorders", "no stock": "backorders",
    "value": "amount", "booking amount": "amount", "ageing": "age", "aging": "age", "days": "age",
    "test drives": "test_drives", "test drive": "test_drives", "drives": "test_drives",
    "retail": "retails", "registrations": "retails", "registered": "retails",
}
_UNITS = {"bookings": "bookings", "enquiries": "enquiries", "qualified": "qualified enquiries",
          "free_stock": "cars in free stock", "backorders": "backorders", "test_drives": "test drive bookings",
          "retails": "retails"}


def _span_words(text: str | None) -> bool:
    from .crm_api import span
    return bool(span(text))


def top(what: str, by: str | None = None, month: str | None = None, date_from: str | None = None,
        date_to: str | None = None, n: int = 5) -> dict:
    """The top n of something, ranked: consultants (by bookings, enquiries,
    test drives or retails),
    models (by bookings, enquiries, free stock or backorders), lead sources (by
    enquiries or qualified), single bookings (by amount), free stock (by age),
    and test drives by car or by executive. A month (default: this calendar
    month) or a span of days; stock is as it stands now."""
    w = re.sub(r"[\s_-]+", " ", (what or "").strip().lower())
    w = _WHAT.get(w, w.replace(" ", "_"))
    if w not in _TOP:
        raise HTTPException(400, "what is one of: consultants, models, sources, bookings, stock, "
                                 "test_drive_cars, test_drive_executives.")
    b = re.sub(r"[\s_-]+", " ", (by or _TOP[w][0]).strip().lower())
    b = _BY.get(b, b.replace(" ", "_"))
    if b not in _TOP[w]:
        raise HTTPException(400, f"{w} can be ranked by: {', '.join(_TOP[w])}.")
    n = max(1, min(int(n or 5), 50))

    if w == "consultants" and b == "retails" and (date_from or date_to or _span_words(month)):
        raise HTTPException(400, "Retails are counted by month: pass a month, e.g. 'September'.")

    rows: list[dict] = []
    about: dict = {}
    scorecard = False        # ranked from a DSR scorecard rather than the calendar
    if w == "stock" or (w == "models" and b == "free_stock"):
        about = {"period": "now"}
        with session() as cx:
            if w == "stock":
                rows = [{"name": f"{r['model']} {r['variant'] or ''}".strip(), "value": r["stock_aging_days"],
                         "chassis": r["chassis_number"], "colour": r["colour"]}
                        for r in cx.execute("""
                            SELECT chassis_number, model, variant, colour, stock_aging_days FROM v_stock
                             WHERE stock_status = 'FREESTOCK' AND stock_aging_days IS NOT NULL
                             ORDER BY stock_aging_days DESC, chassis_number LIMIT %s""", (n,)).fetchall()]
            else:
                rows = [{"name": r["model"], "value": r["free_stock"]} for r in cx.execute(
                    "SELECT model, free_stock FROM v_model_position WHERE free_stock > 0 "
                    "ORDER BY free_stock DESC, model").fetchall()]
    elif w in ("test_drive_cars", "test_drive_executives") or (w == "consultants" and b == "test_drives"):
        about, rows, scorecard = _test_drive_ranking(w, month, date_from, date_to)
    elif w == "bookings":
        where, params, about = _scope(month, date_from, date_to, "b.booking_date", "b")
        with session() as cx:
            rows = [{"name": r["customer_name"] or "Customer not recorded", "value": float(r["booking_amount"]),
                     "model": r["model"], "consultant": r["consultant"],
                     "date": r["booking_date"].isoformat() if r["booking_date"] else None, "status": r["status"]}
                    for r in cx.execute(f"""
                        SELECT b.customer_name, m.name AS model, c.display_name AS consultant,
                               b.booking_amount, b.booking_date, b.fulfilment_status::text AS status
                          FROM booking b
                          LEFT JOIN dim_model m      ON m.model_id      = b.model_id
                          LEFT JOIN dim_consultant c ON c.consultant_id = b.consultant_id
                         WHERE {where} AND b.booking_amount IS NOT NULL
                         ORDER BY b.booking_amount DESC, b.booking_date DESC LIMIT %s""",
                        [*params, n]).fetchall()]
    elif w == "consultants" and not (date_from or date_to) and not _span_words(month):
        # A month: the People page's own figures - bookings, and enquiries as
        # the scorecard counts them.
        board = consultant_leaderboard(month, top=50)
        about = {k: v for k, v in board.items()
                 if k not in ("consultants", "answer", "total_bookings", "consultants_ranked")}
        if b == "bookings":
            rows = [{"name": e["consultant"], "value": e["bookings"], "booking_target": e["booking_target"],
                     "pct_of_target": e["pct_of_target"]} for e in board["consultants"] if e["bookings"]]
        elif b == "retails":
            ranked = sorted((e for e in board["consultants"] if e["retails"]),
                            key=lambda e: (-e["retails"], e["consultant"]))
            rows = [{"name": e["consultant"], "value": e["retails"], "bookings": e["bookings"]} for e in ranked]
        else:
            ranked = sorted((e for e in board["consultants"] if e["enquiries"]),
                            key=lambda e: (-e["enquiries"], e["consultant"]))
            rows = [{"name": e["consultant"], "value": int(e["enquiries"]), "bookings": e["bookings"]} for e in ranked]
    elif w == "sources" and b == "qualified":
        where, params, about = _scope(month, date_from, date_to, "l.created_at", "l")
        with session() as cx:
            rows = [{"name": r["s"], "value": r["n"]} for r in cx.execute(f"""
                SELECT coalesce(s.channel::text, 'Not recorded') AS s, count(*) AS n
                  FROM lead l LEFT JOIN dim_lead_source s ON s.source_id = l.source_id
                 WHERE {where} AND l.qualified_stage = 'Qualified'
                 GROUP BY 1 ORDER BY 2 DESC, 1""", params).fetchall()]
    elif w == "models" and b == "backorders":
        where, params, about = _scope(month, date_from, date_to, "b.booking_date", "b")
        with session() as cx:
            rows = [{"name": r["f"], "value": r["n"]} for r in cx.execute(f"""
                SELECT coalesce(m.family, 'Not recorded') AS f, count(*) AS n
                  FROM booking b LEFT JOIN dim_model m ON m.model_id = b.model_id
                 WHERE {where} AND b.fulfilment_status::text = 'NO_STOCK'
                 GROUP BY 1 ORDER BY 2 DESC, 1""", params).fetchall()]
    else:
        source = bookings_summary if b == "bookings" else leads_summary
        summary = source(month, date_from, date_to)
        field = {"consultants": "by_consultant", "models": "by_model", "sources": "by_source"}[w]
        about = {k: v for k, v in summary.items()
                 if not k.startswith("by_") and k not in ("answer", "total", "qualified")}
        rows = [{"name": k, "value": v} for k, v in summary[field].items()]
        if w == "consultants" and b == "enquiries":
            about["note"] = ("For days, enquiries by consultant count only enquiries with a consultant "
                             "recorded - leads from the CRM export carry none. For a month, the "
                             "scorecard's figures are used.")

    rows = [r for r in rows if r["name"] not in ("Not recorded", "Not assigned")][:n]
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    period = "as it stands now" if about.get("period") == "now" else when(about)
    if w == "bookings":
        title = "biggest bookings by amount"
        fmt = lambda r: f"{r['name']} ({r['model']}) - Rs {r['value']:,.0f}"
    elif w == "stock":
        title = "oldest cars in free stock"
        fmt = lambda r: f"{r['name']} - {r['value']} days"
    elif scorecard:
        title = "consultants by test drives (DSR scorecard)"
        fmt = lambda r: f"{r['name']} - {_against(r['value'], r['target'])}"
    else:
        label = {"consultants": "consultants", "models": "models", "sources": "lead sources",
                 "test_drive_cars": "cars", "test_drive_executives": "executives"}[w]
        title = f"{label} by {_UNITS.get(b, b)}"
        fmt = lambda r: f"{r['name']} - {r['value']}"
    if rows:
        answer = f"Top {len(rows)} {title}, {period}: " + "; ".join(f"{r['rank']}. {fmt(r)}" for r in rows) + "."
        if len(rows) < n:
            answer += f" Only {len(rows)} to rank."
    else:
        answer = f"Nothing to rank for {title}, {period}."
    keep = ("note", "dashboard_month", "calendar_month", "month")
    return {"ranking": title, "period": period, **{k: v for k, v in about.items() if k in keep},
            "rows": rows, "answer": answer}


def _calendar_ranking(w: str, month: str | None, date_from: str | None,
                      date_to: str | None) -> tuple[dict, list[dict]]:
    """Real test drives on the Test Drives calendar, by car or by executive."""
    from .crm_api import _date_clause, span
    if not (date_from or date_to) and span(month):
        date_from = date_to = month
    if date_from or date_to:
        lo, hi = _date_clause("x", date_from, date_to)[1]
        about = {"from": lo.isoformat(), "to": hi.isoformat()}
    else:
        about = resolve_month(month)
        lo, hi = date.fromisoformat(about["from"]), date.fromisoformat(about["to"])
    key = "car_id" if w == "test_drive_cars" else "coalesce(consultant, 'Not assigned')"
    with session() as cx:
        got = cx.execute(f"""
            SELECT {key} AS k, count(*) AS n FROM dsr.test_drive_booking
             WHERE td_date BETWEEN %s AND %s AND status IN ('booked', 'attended', 'no_show')
               AND start_time IS NOT NULL AND NOT sample
             GROUP BY 1 ORDER BY 2 DESC, 1""", (lo, hi)).fetchall()
    from .test_drives import _cars
    names = {c["id"]: c["name"] for c in _cars()}
    rows = [{"name": names.get(r["k"], r["k"]) if w == "test_drive_cars" else r["k"], "value": r["n"]}
            for r in got]
    about["note"] = "Real test drives only; the sample drives are left out."
    return about, rows


def _test_drive_ranking(w: str, month: str | None, date_from: str | None,
                        date_to: str | None) -> tuple[dict, list[dict], bool]:
    """Test drives ranked by car, or by person. A person's test drives for a
    month are what its DSR scorecard records - the calendar began on 6 Oct
    2026 and before that holds only samples, so asked who did the most test
    drives in September there was nothing to rank. Consultants are ranked
    from the scorecard; executives from the calendar's real drives, unless it
    has none for the month. Returns (about, rows, from the scorecard)."""
    by_month = not (date_from or date_to) and not _span_words(month)
    if w == "consultants" and by_month:
        m = resolve_month(month)
        rows = _scorecard_test_drives_by_consultant(m)
        if rows is not None:
            return ({**m, "note": f"From the {when(m)} DSR scorecard - the dealership's record of each "
                                  f"consultant's test drives."}, rows, True)
    about, rows = _calendar_ranking("test_drive_cars" if w == "test_drive_cars" else "test_drive_executives",
                                    month, date_from, date_to)
    if w == "consultants" and by_month:
        about["note"] = (f"No DSR scorecard for {when(about)} yet, so these are the Test Drives calendar's "
                         f"real drives, by executive.")
    if w != "test_drive_cars" and by_month and not [r for r in rows if r["name"] != "Not assigned"]:
        from_card = _scorecard_test_drives_by_consultant(about)
        if from_card:
            return ({**about, "note": f"The Test Drives calendar has no real drives to rank for {when(about)} - "
                                      f"it began on 6 Oct 2026 - so these are the {when(about)} DSR "
                                      f"scorecard's test drives."}, from_card, True)
    return about, rows, False


# ------------------------------------------------------------ scorecards

_CARD = ("leads_target", "total_leads", "td_target", "td_achieved", "booking_target", "booking_achieved",
         "retail_target", "retail_achieved", "finance_target", "finance_achieved",
         "insurance_target", "insurance_achieved")


def _num(v):
    if v is None:
        return None
    f = float(v)
    return int(f) if f.is_integer() else round(f, 1)


def _scorecard_months(cx) -> list[str]:
    """The months with a scorecard loaded, newest first."""
    return [r["label"] for r in cx.execute("""
        SELECT p.label FROM dim_period p
         WHERE EXISTS (SELECT 1 FROM target_consultant_scorecard t WHERE t.period_id = p.period_id)
         ORDER BY p.period_start DESC""").fetchall()]


def _card(cx, consultant_id: int, name: str, m: dict) -> dict | None:
    """One consultant's scorecard for a month (as resolve_month gives it), or
    None when the month's workbook has no row for them. For the month the
    dashboard is set to, the People page's own figures; for another, the
    workbook's, with bookings and enquiries counted as the People page counts
    them. Retails are the month's registrations either way."""
    if m["month"] == m["dashboard_month"]:
        r = cx.execute("SELECT * FROM v_consultant_scorecard WHERE row_kind = 'CONSULTANT' AND consultant = %s",
                       (name,)).fetchone()
        if not r:
            return None
        card = {k: _num(r[k]) for k in _CARD}
    else:
        r = cx.execute("""
            SELECT max(leads_target)       FILTER (WHERE is_primary_channel) AS leads_target,
                   sum(total_leads)                                          AS total_leads,
                   max(td_target)          FILTER (WHERE is_primary_channel) AS td_target,
                   sum(td_achieved)                                          AS td_achieved,
                   max(booking_target)     FILTER (WHERE is_primary_channel) AS booking_target,
                   max(retail_target)      FILTER (WHERE is_primary_channel) AS retail_target,
                   sum(retail_achieved)                                      AS retail_achieved,
                   max(finance_target)     FILTER (WHERE is_primary_channel) AS finance_target,
                   max(finance_achieved)   FILTER (WHERE is_primary_channel) AS finance_achieved,
                   max(insurance_target)   FILTER (WHERE is_primary_channel) AS insurance_target,
                   max(insurance_achieved) FILTER (WHERE is_primary_channel) AS insurance_achieved,
                   count(*) AS n
              FROM target_consultant_scorecard
             WHERE consultant_id = %s AND period_id = %s AND row_kind = 'CONSULTANT'""",
            (consultant_id, m["period_id"])).fetchone()
        if not r["n"]:
            return None
        card = {k: _num(r[k]) for k in _CARD if k != "booking_achieved"}
        # Bookings and enquiries as the People page counts them for its month.
        card["booking_achieved"] = cx.execute(
            "SELECT count(*) AS n FROM booking WHERE consultant_id = %s AND period_id = %s",
            (consultant_id, m["period_id"])).fetchone()["n"]
        card["total_leads"] = (card["total_leads"] or 0) + cx.execute(
            "SELECT count(*) AS n FROM lead WHERE consultant_id = %s AND period_id = %s AND origin = 'MANUAL'",
            (consultant_id, m["period_id"])).fetchone()["n"]
    card["retail_achieved"] = _month_retails(cx, m, consultant_id)
    card["consultant"] = name
    return card


def consultant_scorecard(name: str, month: str | None = None) -> dict:
    """One consultant's scorecard - enquiries, test drives, bookings, retails,
    finance and insurance against target - for any month that has one.

    The scorecard comes from the month's workbook, and is the dealership's own
    record of a consultant's test drives: the Test Drives section began on
    6 Oct 2026, so asked for Sanjeev's September test drives the agent found
    none there and answered 0 - the scorecard says 10. With no month, the
    latest month with a scorecard; for the month the dashboard is set to, the
    People page's own figures."""
    with session() as cx:
        months = _scorecard_months(cx)
    if not months:
        raise HTTPException(404, "No scorecards have been loaded.")
    m = resolve_month(month or months[0])
    have = ", ".join(when({"month": x, "period_id": 0}) for x in months)
    if m["month"] not in months:
        return {**_note(m), "answer": f"No scorecard for {when(m)} yet - its workbook has not been loaded. "
                                      f"Scorecards: {have}."}
    with session() as cx:
        people = cx.execute("""SELECT consultant_id, display_name FROM dim_consultant
                                WHERE display_name ILIKE %s ORDER BY is_active DESC, display_name""",
                            (f"%{name.strip()}%",)).fetchall()
        if not people:
            raise HTTPException(404, f"No consultant matching {name!r}.")
        cards = [c for c in (_card(cx, p["consultant_id"], p["display_name"], m) for p in people[:3]) if c]
    if not cards:
        return {**_note(m), "answer": f"No scorecard row for {name} in {when(m)}."}

    first = cards[0]
    answer = (f"{first['consultant']}, {when(m)}: " + ", ".join((
        _against(first["td_achieved"] or 0, first["td_target"], "test drives"),
        _against(first["booking_achieved"] or 0, first["booking_target"], "bookings"),
        _against(first["retail_achieved"] or 0, first["retail_target"], "retails"),
        _against(first["total_leads"] or 0, first["leads_target"], "enquiries"))) + ".")
    return {**_note(m), "scorecards": cards, "answer": answer,
            "source": "The month's DSR scorecard - the dealership's record of each consultant's test drives."}


def _scorecard_test_drives_by_consultant(m: dict) -> list[dict] | None:
    """Consultants' test drives for a month from its DSR scorecard, most
    first; None when the month has no scorecard."""
    if not m.get("period_id"):
        return None
    with session() as cx:
        people = cx.execute("""
            SELECT DISTINCT c.consultant_id, c.display_name FROM dim_consultant c
              JOIN target_consultant_scorecard t ON t.consultant_id = c.consultant_id
             WHERE t.period_id = %s AND t.row_kind = 'CONSULTANT'""", (m["period_id"],)).fetchall()
        if not people:
            return None
        cards = [c for c in (_card(cx, p["consultant_id"], p["display_name"], m) for p in people) if c]
    return sorted(({"name": c["consultant"], "value": c["td_achieved"], "target": c["td_target"]}
                   for c in cards if c["td_achieved"]), key=lambda r: (-r["value"], r["name"]))


# ------------------------------------------------------------ a month's headline

# The Test Drives section's first day. Before it the calendar holds only sample
# drives, and a month's test drives are the ones its DSR scorecard records.
CALENDAR_START = date(2026, 10, 6)


def _dealership_test_drives(cx, m: dict) -> dict | None:
    """A month's test drives as the dashboard's headline counts them
    (v_sales_funnel): the month's scorecard total plus test drives entered by
    hand. None when the month's workbook - and so its scorecard - is not loaded."""
    g = _grand_total(cx, m["period_id"])
    if not g["n"]:
        return None
    by_hand = cx.execute("""SELECT count(*) AS n FROM test_drive WHERE origin = 'MANUAL'
                              AND (td_date IS NULL OR td_date BETWEEN %s AND %s)""",
                         (m["from"], m["to"])).fetchone()["n"]
    return {"test_drives": _num((g["test_drives"] or 0) + by_hand), "target": _num(g["test_drive_target"])}


def scorecard_test_drives(day: date, name: str | None = None) -> dict | None:
    """The test drives the DSR scorecard records for the month holding `day` -
    the dealership's, or one consultant's - with a sentence that says so. None
    when that month has no scorecard, or no row for the consultant."""
    m = resolve_month(day.strftime("%Y-%m"))
    if m["period_id"] is None:
        return None
    with session() as cx:
        if name and name.strip():
            who = cx.execute("""SELECT consultant_id, display_name FROM dim_consultant
                                 WHERE display_name ILIKE %s ORDER BY is_active DESC, display_name LIMIT 1""",
                             (f"%{name.strip()}%",)).fetchone()
            card = _card(cx, who["consultant_id"], who["display_name"], m) if who else None
            if not card:
                return None
            done = card["td_achieved"] or 0
            return {"month": m["month"], "consultant": card["consultant"], "test_drives": done,
                    "target": card["td_target"],
                    "answer": f"{card['consultant']}, {when(m)}: "
                              f"{_against(done, card['td_target'], 'test drives')} by the DSR scorecard."}
        tds = _dealership_test_drives(cx, m)
    if not tds:
        return None
    return {"month": m["month"], **tds,
            "answer": f"{when(m)}: {_against(tds['test_drives'], tds['target'], 'test drives')} "
                      f"by the DSR scorecard."}


def month_snapshot(month: str | None = None) -> dict:
    """The dashboard's headline for any month - enquiries, test drives,
    bookings and retails against the month's targets - counted as the
    dashboard counts them for the month it is set to (v_sales_funnel,
    v_daily_kpi), so for that month they are the dashboard's own figures.
    Stock is as it stands now. With no month, the month the dashboard is set to.

    Asked how many test drives the dealership did in September, the agent had
    only the Test Drives calendar, which began on 6 Oct 2026, and answered 0;
    the September scorecard says 76. Asked for September's retails it gave the
    bookings since retailed (12); the month's retails are 17."""
    m = resolve_month(month or "active")
    if m["period_id"] is None:
        return {**m, "note": f"Nothing has been filed under {m['month']} yet.",
                "answer": f"Nothing recorded for {when(m)} yet."}
    with session() as cx:
        f = dict(cx.execute("""
            SELECT (SELECT count(*) FROM lead WHERE period_id = %(p)s)                          AS enquiries,
                   (SELECT count(*) FROM lead
                     WHERE period_id = %(p)s AND qualified_stage = 'Qualified')                 AS qualified,
                   (SELECT count(*) FROM booking WHERE period_id = %(p)s)                       AS bookings,
                   (SELECT count(*) FROM booking
                     WHERE period_id = %(p)s AND fulfilment_status = 'NO_STOCK')                AS backorders,
                   (SELECT count(*) FROM booking
                     WHERE period_id = %(p)s AND crm_entry_done IS FALSE)                       AS bookings_missing_crm_entry,
                   (SELECT sum(booking_amount) FROM booking WHERE period_id = %(p)s)            AS booking_amount_collected,
                   (SELECT count(*) FROM vehicle WHERE stock_status = 'FREESTOCK')              AS free_stock,
                   (SELECT count(*) FROM vehicle WHERE stock_status = 'ALLOTED')                AS allotted_stock,
                   (SELECT count(*) FROM vehicle
                     WHERE stock_status IN ('FREESTOCK', 'ALLOTED') AND stock_aging_days > 90)  AS stock_over_90_days
            """, {"p": m["period_id"]}).fetchone())
        f["retails"] = _month_retails(cx, m)
        g = _grand_total(cx, m["period_id"])
        tds = _dealership_test_drives(cx, m)
    if f["booking_amount_collected"] is not None:
        f["booking_amount_collected"] = float(f["booking_amount_collected"])
    f["test_drives"] = tds["test_drives"] if tds else None
    f.update({k: _num(g[k]) for k in ("enquiry_target", "test_drive_target", "booking_target", "retail_target")})
    f["enquiry_to_booking_pct"] = round(100 * f["bookings"] / f["enquiries"], 1) if f["enquiries"] else None
    f["booking_to_retail_pct"] = round(100 * f["retails"] / f["bookings"], 1) if f["bookings"] else None

    answer = f"{when(m)}: " + ", ".join(
        [_against(f["enquiries"], f["enquiry_target"], "enquiries")]
        + ([_against(f["test_drives"], f["test_drive_target"], "test drives")] if tds else [])
        + [_against(f["bookings"], f["booking_target"], "bookings"),
           _against(f["retails"], f["retail_target"], "retails")]) + "."
    out = {**_note(m), "figures": f,
           "test_drives_source": ("The month's DSR scorecard total, as the dashboard's headline counts it - the "
                                  "dealership's record of test drives. The Test Drives calendar began on 6 Oct 2026."),
           "retails_note": "Retails are cars registered in the month, as the scorecard counts them - not bookings "
                           "marked RETAILED.",
           "stock_note": "free_stock, allotted_stock and stock_over_90_days are as the stock stands now; "
                         "stock_over_90_days counts free and allotted cars.",
           "backorders_note": "backorders: the month's bookings still waiting for a car. Every open order waiting "
                              "for a car, from any month, is in get_action_list."}
    if not tds:
        out["test_drives_source"] = f"No scorecard for {when(m)} yet, so no scorecard test drives or targets."
        answer += f" No scorecard for {when(m)} yet, so no test-drive figure or targets from it"
        if date.fromisoformat(m["to"]) >= CALENDAR_START:
            from .test_drives import agent_test_drives
            r = agent_test_drives(month=m["month"], include_samples=False, limit=1)["real"]
            answer += (f"; on the Test Drives calendar: {r['attended']} attended, "
                       f"{r['booked_upcoming']} booked ahead, {r['no_show']} no-show")
        answer += "."
    out["answer"] = answer
    return out
