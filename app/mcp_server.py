"""
MCP (Model Context Protocol) surface for the Perfox "Dashboard Insights" agent.

A single JSON-RPC endpoint, `POST /mcp`, implementing the three methods a
Perfox Integration node needs: `initialize`, `tools/list`, `tools/call`. Each
tool is a thin wrapper around the read functions already built for the
`/agent/*` surface (app/main.py) and the CRM agent surface (app/crm_api.py) -
no new queries, just JSON-RPC dispatch onto what already exists.

The `/agent/*` functions live in app.main, which imports this module's router
(app.main:93-97-style `include_router`), so importing them back at module
load time would be circular - they're imported lazily inside each handler
instead.
"""

from __future__ import annotations

import os
import re
import secrets
from typing import Any, Callable, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel

from .crm_api import (
    FetchBookingsPayload,
    FetchLeadsPayload,
    fetch_bookings_for_agent,
    fetch_leads_for_agent,
)


def require_mcp_token(
    authorization: Optional[str] = Header(None),
) -> None:
    """
    Bearer-only guard for the /mcp surface, mirroring require_agent_key
    (app/crm_api.py). Perfox's "Register MCP server" screen wants a single
    bearer credential, so this doesn't also accept X-API-Key.

    Unset PERFOX_MCP_TOKEN leaves the route open, same convention as
    AGENT_API_KEY - fine for local dev, not for the deployed URL Perfox
    actually calls.
    """
    expected = os.environ.get("PERFOX_MCP_TOKEN", "").strip()
    if not expected:
        return

    sent = ""
    if authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            sent = token.strip()

    if not sent or not secrets.compare_digest(sent, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing MCP token.")


router = APIRouter(prefix="/mcp", tags=["mcp"], dependencies=[Depends(require_mcp_token)])


class JsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: Optional[int | str] = None
    method: str
    params: Optional[dict] = None


# ---------------------------------------------------------------------------
# Tool implementations - each takes the JSON-RPC `arguments` dict and returns
# a plain JSON-able value. Business logic stays in app.main / app.crm_api;
# these just adapt call shape.
# ---------------------------------------------------------------------------

def _tool_get_dealership_snapshot(args: dict) -> Any:
    from .agent_insights import month_snapshot
    return month_snapshot(args.get("month"))


def _tool_get_consultant_scorecard(args: dict) -> Any:
    from .agent_insights import consultant_scorecard
    name = args.get("name")
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    return consultant_scorecard(name, args.get("month"))


def _period_arg(args: dict) -> str:
    """get_leads / get_bookings take a month as 'active', 'all', or anything
    resolve_month reads ('current', 'last', 'September', 'SEP2026')."""
    want = (args.get("period") or args.get("month") or "active").strip()
    if want.lower() in ("active", "all"):
        return want
    from .agent_insights import resolve_month
    return resolve_month(want)["month"]


def _days_args(args: dict) -> tuple[str | None, str | None]:
    """date / date_from / date_to - and a span in words passed as the month
    ("this week" as period), which is days, not a month."""
    from .crm_api import span
    for k in ("period", "month"):
        if span(args.get(k)) and not (args.get("date") or args.get("date_from") or args.get("date_to")):
            return args[k], args[k]
    return (args.get("date_from") or args.get("date"), args.get("date_to") or args.get("date"))


_CHASE = {"stock_past_retail_deadline": "cars in free stock past their retail deadline",
          "ageing_over_90_days": "cars over 90 days in free stock",
          "backorders": "backorders (booked, no car yet)",
          "bookings_missing_crm_entry": "bookings missing a CRM entry"}


def _tool_get_action_list(args: dict) -> Any:
    """Totals, and the ten most pressing of each list - the whole of it ran to
    22 KB, more than a small model reads well."""
    from .main import agent_action_list
    full = agent_action_list()
    if not isinstance(full, dict):
        return full
    out = {k: {"total": len(v), "first_10": v[:10]} for k, v in full.items() if isinstance(v, list)}
    out["answer"] = "To chase: " + "; ".join(
        f"{len(full[k])} {label}" for k, label in _CHASE.items() if isinstance(full.get(k), list)) + "."
    return out


def _tool_get_vehicle_availability(args: dict) -> Any:
    """Free stock matching a model, trim and colour. An empty list used to
    come back bare, and a model had to guess what it meant; now it is said."""
    from .main import agent_availability
    rows = agent_availability(model=args.get("model"), variant=args.get("variant"), colour=args.get("colour"))
    asked = " ".join(str(args.get(k)) for k in ("model", "variant", "colour") if args.get(k)) or "any car"
    out = {"asked_for": asked, "found": len(rows), "cars": rows}
    if not rows:
        from .test_drives import _cars
        model = (args.get("model") or "").strip().lower()
        families = [c["name"] for c in _cars()]
        sold = any(model and (model in f.lower() or f.lower().split()[0] in model) for f in families)
        out["answer"] = (f"{args.get('model')} is not a model this dealership sells. Models: {', '.join(families)}."
                         if model and not sold else f"No {asked} in free stock right now.")
    else:
        out["answer"] = f"{len(rows)} match{'es' if len(rows) != 1 else ''} for {asked} in free stock."
    return out


def _tool_get_order_status(args: dict) -> Any:
    from .main import agent_order_status
    # PII POLICY (2026-10-08): phone numbers are not stored, so the lookup is
    # by name only (see agent_order_status in app/main.py).
    name = args.get("name")
    if not name:
        raise HTTPException(status_code=400,
                            detail="Ask the customer for the name on the booking - "
                                   "phone numbers are not stored, so orders are found by name.")
    rows = agent_order_status(name=name, mobile=None)
    who = name
    return {"searched_for": who, "found": len(rows), "orders": rows,
            "answer": (f"{len(rows)} booking{'s' if len(rows) != 1 else ''} found for {who}." if rows
                       else f"No booking found for {who}. Check the spelling, "
                            f"or the customer may have enquired without booking.")}


def _tool_get_model_catalogue(args: dict) -> Any:
    """Each model family with its trims, each counted once. As catalogue rows
    the Taigun read as 20 variants - the Taigun and the Taigun facelift list
    the same trims, and some are spelled twice - and the agent answered 12 and
    listed 11. It is 10 trims."""
    from .main import agent_model_catalogue
    from .test_drives import _cars, distinct_trims
    want = (args.get("model") or "").strip().lower()
    groups: dict[str, list[dict]] = {}
    for r in agent_model_catalogue():
        groups.setdefault((r.get("family") or r.get("model") or "").strip().upper(), []).append(r)
    families = []
    # Every model sold, as the board names them - the Tiguan R-Line has no
    # trims in the catalogue, and listing only what had trims left it out.
    for car in _cars():
        rows = groups.get(car["family"].upper(), [])
        names = [car["name"].lower(), car["family"].lower()] + [(r.get("model") or "").lower() for r in rows]
        if want and not any(want in n or n in want for n in names if n):
            continue
        trims = distinct_trims([(r.get("variant"), r.get("long_model_text")) for r in rows])
        families.append({
            "model": car["name"],
            "listed_as": sorted({r.get("model") for r in rows if r.get("model")}),
            "trims": trims,
            "trim_count": len(trims),
            "free_units": sum(int(r.get("free_units") or 0) for r in rows),
        })
    if not families:
        return {"families": [], "answer": f"{args.get('model')} is not a model this dealership sells."}
    return {
        "families": families,
        "note": "Each trim is counted once: the Taigun and the Taigun facelift (FL) list the same trims.",
        "answer": "; ".join(f"{f['model']}: " + (f"{f['trim_count']} trim{'s' if f['trim_count'] != 1 else ''}"
                                                   if f["trim_count"] else "trims not listed in the catalogue")
                            for f in families) + ".",
    }


def _tool_get_leads(args: dict) -> Any:
    status = args.get("status", "New")
    rating = args.get("rating")
    if (status or "").strip().lower() in ("hot", "warm", "cold"):     # a rating, not a status
        rating, status = status, "all"
    date_from, date_to = _days_args(args)
    payload = FetchLeadsPayload(
        limit=args.get("limit", 50),
        status=status,
        period="all" if date_from or date_to else _period_arg(args),
        search=args.get("search"),
        date_from=date_from,
        date_to=date_to,
        rating=rating,
    )
    return _one_line_per_enquiry(fetch_leads_for_agent(payload))


_LEAD_TYPES = {"test_drive": "Test drive", "general_enquiry": "General enquiry", "service": "Service",
               "insurance": "Insurance", "rental": "Rental", "career": "Career"}


def _one_line_per_enquiry(rows: list[dict]) -> dict:
    """The phone agent saves one lead per need, so a caller who wants to order
    a Virtus and test-drive it - or asks about two cars - becomes two leads
    seconds apart, and a list showed the same person twice. Leads from one
    customer (phone and first name: test calls put several names on one
    number) on the same day are one line here, naming every car and saying
    how many leads it holds and what each asked for. The database keeps them
    all, and the dashboard counts each."""
    lines: list[dict] = []
    by_key: dict[tuple, dict] = {}
    for r in rows:
        model = r.get("model") or r.get("model_of_interest")   # a model the catalogue did not match
        phone = re.sub(r"\D", "", r.get("mobile") or "")[-10:]
        first = (r.get("lead_name") or "").strip().split(" ")[0].lower()
        key = (phone or (r.get("lead_name") or "").strip().lower(), first, str(r.get("created_at") or "")[:10])
        need = {"lead_id": r.get("lead_id"), "car": model,
                "type": _LEAD_TYPES.get(r.get("lead_type") or "", r.get("lead_type")),
                "note": r.get("enquiry_note")}
        line = by_key.get(key)
        if line:
            line["leads"] += 1
            line["needs"].append(need)
            if model and model.upper() not in (m.upper() for m in line["cars"]):
                line["cars"].append(model)
                line["model"] = ", ".join(line["cars"])
            continue
        line = {k: v for k, v in r.items() if k not in ("model_of_interest", "lead_type", "enquiry_note")}
        line.update(model=model, cars=[model] if model else [], leads=1, needs=[need])
        by_key[key] = line
        lines.append(line)
    return {
        "order": "newest first - a list, not a ranking. For 'top' or 'most' use get_top.",
        "customers": len(lines),
        "leads": len(rows),
        "note": ("One line per customer per day. 'leads' on a line is how many leads it holds - a caller "
                 "who asked for two things, or about two cars, is saved as two leads, and the dashboard "
                 "counts both. 'model' names every car on the line."),
        "lines": lines,
    }


def _tool_get_bookings(args: dict) -> Any:
    date_from, date_to = _days_args(args)
    payload = FetchBookingsPayload(
        limit=args.get("limit", 50),
        period="all" if date_from or date_to else _period_arg(args),
        search=args.get("search"),
        status=args.get("status"),
        date_from=date_from,
        date_to=date_to,
    )
    rows = fetch_bookings_for_agent(payload)
    return {"order": "newest booking first - a list, not a ranking. For 'top', 'biggest' or 'most' use get_top; "
                     "for counts use get_bookings_summary.",
            "count": len(rows), "bookings": rows}


def _yes(value: Any, default: bool = True) -> bool:
    """A flag as an agent may send it: true/false, or 'true'/'no'/'0'."""
    if value is None:
        return default
    return str(value).strip().lower() not in ("false", "no", "0", "off")


def _tool_get_test_drives(args: dict) -> Any:
    from .test_drives import agent_test_drives
    return agent_test_drives(
        date_=args.get("date"),
        date_from=args.get("date_from"),
        date_to=args.get("date_to"),
        status=args.get("status"),
        car=args.get("car"),
        search=args.get("search"),
        include_samples=_yes(args.get("include_samples")),
        limit=int(args.get("limit") or 60),
        month=args.get("month"),
        executive=args.get("executive"),
    )


def _tool_get_bookings_summary(args: dict) -> Any:
    from .agent_insights import bookings_summary
    date_from, date_to = _days_args(args)
    return bookings_summary(month=args.get("month"), date_from=date_from, date_to=date_to)


def _tool_get_top(args: dict) -> Any:
    from .agent_insights import top
    date_from, date_to = _days_args(args)
    return top(what=args.get("what") or "", by=args.get("by"), month=args.get("month"),
               date_from=date_from, date_to=date_to, n=int(args.get("top") or args.get("n") or 5))


def _tool_get_leads_summary(args: dict) -> Any:
    from .agent_insights import leads_summary
    date_from, date_to = _days_args(args)
    return leads_summary(month=args.get("month"), date_from=date_from, date_to=date_to)


def _tool_get_consultant_leaderboard(args: dict) -> Any:
    from .agent_insights import consultant_leaderboard
    return consultant_leaderboard(month=args.get("month"), top=int(args.get("top") or 10))


def _tool_get_test_drive_enquiries(args: dict) -> Any:
    from .test_drives import agent_test_drive_enquiries
    return agent_test_drive_enquiries(
        car=args.get("car"),
        include_samples=_yes(args.get("include_samples")),
        limit=int(args.get("limit") or 60),
    )


TOOLS: list[dict] = [
    {
        "name": "get_top",
        "description": "RANKINGS - use for every 'top', 'best', 'most', 'biggest', 'highest', 'oldest' or 'rank' question. Returns the ranked rows and a ready 'answer' sentence to repeat. what: consultants (by bookings, enquiries, test_drives or retails - test drives from the month's DSR scorecard), models (by bookings, enquiries, free_stock or backorders), sources (by enquiries or qualified), bookings (single bookings by amount - 'top 5 bookings'), stock (oldest free stock by age), test_drive_cars or test_drive_executives (by test drive bookings). A month (default: this calendar month) or days; stock is as it stands now.",
        "input_schema": {
            "type": "object",
            "properties": {
                "what": {"type": "string", "description": "consultants, models, sources, bookings, stock, test_drive_cars or test_drive_executives"},
                "by": {"type": "string", "description": "What to rank by: bookings, enquiries, test_drives, retails, qualified, free_stock, backorders; leave out for the usual one (bookings, enquiries, amount or age)"},
                "top": {"type": "integer", "description": "How many, default 5"},
                "month": {"type": "string", "description": "'current' (default), 'last', 'next', a month name or label like 'September' / 'SEP2026', or 'active' (the month the dashboard is set to)"},
                "date": {"type": "string", "description": "Days instead of a month: 'today', 'yesterday', 'this week', 'last week', 'last 7 days', or YYYY-MM-DD"},
                "date_from": {"type": "string", "description": "First day of a span"},
                "date_to": {"type": "string", "description": "Last day of a span"},
            },
            "required": ["what"],
        },
    },
    {
        "name": "get_dealership_snapshot",
        "description": "The dealership's headline figures for a month - enquiries, test drives, bookings and retails against the month's targets, conversion - and stock as it stands now. Use it for 'how many test drives / retails / bookings did we do in <month>'. Test drives are the month's DSR scorecard total (the Test Drives calendar began on 6 Oct 2026); retails are cars registered in the month, not bookings marked retailed. Leave month out for the month the dashboard is set to; the reply says which month.",
        "input_schema": {"type": "object", "properties": {
            "month": {"type": "string", "description": "A month name or label like 'September' / 'SEP2026', 'current', 'last', or 'active' (the month the dashboard is set to, the default)"},
        }},
    },
    {
        "name": "get_consultant_scorecard",
        "description": "One sales consultant's scorecard against target - test drives, bookings, retails, enquiries, finance, insurance - for a month (default: the latest month with a scorecard). Use it for 'how many test drives did <consultant> do in <month>': the scorecard is the dealership's record of a consultant's test drives; the Test Drives section only began on 6 Oct 2026. To rank consultants, use get_top.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Consultant name, full or partial"},
                "month": {"type": "string", "description": "A month name or label like 'September' / 'SEP2026', 'last', or 'active'; leave out for the latest scorecard"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_action_list",
        "description": "What needs chasing today: stock past its retail deadline, stock aging over 90 days, backorders, and bookings missing a CRM entry.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_vehicle_availability",
        "description": "Is a specific car in stock right now? Filter by model, variant/trim, and/or colour.",
        "input_schema": {
            "type": "object",
            "properties": {
                "model": {"type": "string", "description": "Model or family, e.g. Virtus, Taigun"},
                "variant": {"type": "string", "description": "Trim, e.g. GT Line AT"},
                "colour": {"type": "string", "description": "Colour name, e.g. Candy White"},
            },
        },
    },
    {
        "name": "get_order_status",
        # PII POLICY (2026-10-08): was "name and/or mobile number". Phone
        # numbers are not stored, so the tool takes a name only - which also
        # stops the agent sending the customer's number to this server at all.
        "description": "A customer's booking/order status, found by the name on the booking. "
                       "Phone numbers and emails are not stored, so ask for the name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Customer name, full or partial"},
            },
            "required": ["name"],
        },
    },
    {
        "name": "get_model_catalogue",
        "description": "Every model family the dealership sells, with its trims (variants) each counted once and free stock per family - 'how many variants of the Taigun' is its trim_count. Pass model for one family.",
        "input_schema": {"type": "object", "properties": {
            "model": {"type": "string", "description": "One model, e.g. Taigun or Virtus; leave out for all"},
        }},
    },
    {
        "name": "get_leads",
        "description": "A LIST of enquiries/leads, newest first - not a ranking (for top/most use get_top; for counts get_leads_summary). status 'hot', 'warm' or 'cold' reads the lead rating. Live from the database. For a day or days (today, yesterday, a date) pass date or date_from/date_to: that reads those days whatever reporting month the dashboard is set to. Otherwise reads the active (or a named) reporting month. Optionally filter by status or search by name. Leads from one customer on the same day come as one line, naming every car, with how many leads it holds and what each asked for - list lines, not leads. For counts use get_leads_summary.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "A day or a span in words: 'today', 'yesterday', 'this week', 'last week', 'last 7 days', 'this month', or YYYY-MM-DD (India time)"},
                "date_from": {"type": "string", "description": "First day of a span, as for date"},
                "date_to": {"type": "string", "description": "Last day of a span, as for date"},
                "limit": {"type": "integer", "description": "Max rows, default 50"},
                "status": {"type": "string", "description": "Lead status, default 'New'; 'all' for every status"},
                "period": {"type": "string", "description": "Month: 'current' (this calendar month), 'last', a month name or label like 'September' / 'SEP2026', 'active' (the month the dashboard is set to; the default), or 'all'. Ignored when a date is given"},
                "search": {"type": "string", "description": "Matches the lead's name"},
            },
        },
    },
    {
        "name": "get_bookings",
        "description": "A LIST of bookings, newest first - not a ranking (for top/biggest/most use get_top; for counts get_bookings_summary). Live from the database. For a day or days pass date or date_from/date_to (on the booking date), whatever reporting month the dashboard is set to. Otherwise reads the active (or a named) reporting month. Optionally filter by fulfilment status or search by customer name.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "A day or a span in words: 'today', 'yesterday', 'this week', 'last week', 'last 7 days', 'this month', or YYYY-MM-DD (India time)"},
                "date_from": {"type": "string", "description": "First day of a span, as for date"},
                "date_to": {"type": "string", "description": "Last day of a span, as for date"},
                "limit": {"type": "integer", "description": "Max rows, default 50"},
                "period": {"type": "string", "description": "Month: 'current' (this calendar month), 'last', a month name or label like 'September' / 'SEP2026', 'active' (the month the dashboard is set to; the default), or 'all'. Ignored when a date is given"},
                "search": {"type": "string", "description": "Matches the customer's name"},
                "status": {"type": "string", "description": "booked, no_stock (backorder), allotted, retailed or cancelled"},
            },
        },
    },
    {
        "name": "get_bookings_summary",
        "description": "Booking COUNTS for a month (default: this calendar month) or a span of days: the total, by model (as the dashboard's Inventory page counts them, e.g. TAIGUN includes Taigun FL), by consultant and by fulfilment status - and for a month, its retails (cars registered), which are not the RETAILED status count. Use this for any 'how many bookings' question - never count rows yourself.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "'current' (default, this calendar month), 'last', a month name or label like 'September' / 'SEP2026', or 'active' (the month the dashboard is set to)"},
                "date": {"type": "string", "description": "Days instead of a month: 'today', 'yesterday', 'this week', 'last week', 'last 7 days', or YYYY-MM-DD"},
                "date_from": {"type": "string", "description": "First day of a span"},
                "date_to": {"type": "string", "description": "Last day of a span"},
            },
        },
    },
    {
        "name": "get_leads_summary",
        "description": "Enquiry/lead COUNTS for a month (default: this calendar month) or a span of days: the total, how many qualified, by source channel (CRM, WALKIN, TELE, DIGITAL, REFERRAL...), by model and by consultant (for a month, as the scorecard counts a consultant's enquiries). Use this for any 'how many leads/enquiries' question - never count rows yourself.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "'current' (default, this calendar month), 'last', a month name or label like 'September' / 'SEP2026', or 'active' (the month the dashboard is set to)"},
                "date": {"type": "string", "description": "Days instead of a month: 'today', 'yesterday', 'this week', 'last week', 'last 7 days', or YYYY-MM-DD"},
                "date_from": {"type": "string", "description": "First day of a span"},
                "date_to": {"type": "string", "description": "Last day of a span"},
            },
        },
    },
    {
        "name": "get_consultant_leaderboard",
        "description": "Sales consultants ranked as the dashboard's People page ranks them (by bookings, then retails) for a month (default: this calendar month), with bookings, booking target, % of target and enquiries. Use for 'top consultants', 'who is leading', 'rank the team'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "month": {"type": "string", "description": "'current' (default, this calendar month), 'last', a month name or label like 'September' / 'SEP2026', or 'active' (the month the dashboard is set to)"},
                "top": {"type": "integer", "description": "How many to list, default 10"},
            },
        },
    },
    {
        "name": "get_test_drives",
        "description": "Test drives from the dashboard's Test Drives section, live from the database, for a day (default today), a span of up to 62 days, or a month: each drive with day, time, car, customer, executive, place and status, plus test-drive enquiries. Counts come ready-made for real drives and for samples apart: bookings (drives given a slot: booked, attended or no-show), cancelled, enquiries waiting and missed enquiries. Also the section's headline figures.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "A day or a span in words: 'today' (default), 'tomorrow', 'yesterday', 'this week', 'next week', 'next 7 days', or YYYY-MM-DD"},
                "date_from": {"type": "string", "description": "First day of a span, as for date"},
                "date_to": {"type": "string", "description": "Last day of a span, as for date"},
                "month": {"type": "string", "description": "A whole month instead: 'current' (this calendar month), 'last', or a month name or label like 'October' / 'OCT2026'"},
                "status": {"type": "string", "description": "bookings (any drive given a slot), booked, attended, no_show, cancelled or enquiry; omit for all"},
                "car": {"type": "string", "description": "Taigun, Virtus, Tayron, Tiguan R-Line or Golf GTI"},
                "executive": {"type": "string", "description": "A sales executive's name, full or partial: only their drives, counted"},
                "search": {"type": "string", "description": "Customer name, or 4+ digits of their phone"},
                "include_samples": {"type": "boolean", "description": "Include the made-up sample drives (default true)"},
                "limit": {"type": "integer", "description": "Max drives listed, default 60"},
            },
        },
    },
    {
        "name": "get_test_drive_enquiries",
        "description": "Test-drive enquiries waiting for a time, live from the database: customers who asked for a test drive with no slot booked yet, with the day and time they asked for and the day the enquiry came in. Also promised_on_calls: calls where the agent promised a test drive and nothing was saved for the caller.",
        "input_schema": {
            "type": "object",
            "properties": {
                "car": {"type": "string", "description": "Taigun, Virtus, Tayron, Tiguan R-Line or Golf GTI"},
                "include_samples": {"type": "boolean", "description": "Include the made-up sample enquiries (default true)"},
                "limit": {"type": "integer", "description": "Max enquiries listed, default 60"},
            },
        },
    },
]

# FIX (2026-10-08): tools/list sent only `input_schema`. That is the key
# Perfox's own docs ask for, but the MCP specification - and therefore any
# standard MCP client pointed at this server - reads `inputSchema`, and sees a
# tool with no arguments. Both keys are now sent, so Perfox keeps working
# unchanged and spec clients get the schema too.
for _tool in TOOLS:
    _tool["inputSchema"] = _tool["input_schema"]

TOOL_HANDLERS: dict[str, Callable[[dict], Any]] = {
    "get_dealership_snapshot": _tool_get_dealership_snapshot,
    "get_consultant_scorecard": _tool_get_consultant_scorecard,
    "get_action_list": _tool_get_action_list,
    "get_vehicle_availability": _tool_get_vehicle_availability,
    "get_order_status": _tool_get_order_status,
    "get_model_catalogue": _tool_get_model_catalogue,
    "get_leads": _tool_get_leads,
    "get_bookings": _tool_get_bookings,
    "get_top": _tool_get_top,
    "get_bookings_summary": _tool_get_bookings_summary,
    "get_leads_summary": _tool_get_leads_summary,
    "get_consultant_leaderboard": _tool_get_consultant_leaderboard,
    "get_test_drives": _tool_get_test_drives,
    "get_test_drive_enquiries": _tool_get_test_drive_enquiries,
}


# ---------------------------------------------------------------------------
# JSON-RPC dispatch
# ---------------------------------------------------------------------------

def _rpc_result(id_: Any, result: Any) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _rpc_error(id_: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": id_, "error": {"code": code, "message": message}}


@router.post("", response_model=None)
def mcp_rpc(body: JsonRpcRequest) -> dict | Response:
    # A notification - notifications/initialized, sent once the handshake is
    # done - wants no answer: Streamable HTTP expects 202 and an empty body,
    # where an error reply can make a client drop the connection.
    if body.method.startswith("notifications/"):
        return Response(status_code=202)

    if body.method == "ping":
        return _rpc_result(body.id, {})

    if body.method == "initialize":
        return _rpc_result(body.id, {
            "protocolVersion": "2024-11-05",
            "serverInfo": {"name": "elite-dashboard-mcp", "version": "1.0.0"},
            "capabilities": {"tools": {}},
        })

    if body.method == "tools/list":
        # The MCP spec names a tool's parameters inputSchema; this server has
        # always sent input_schema. Both, so a client reading either - Perfox,
        # an MCP proxy - sees what each tool takes.
        return _rpc_result(body.id, {"tools": [{**t, "inputSchema": t["input_schema"]} for t in TOOLS]})

    if body.method == "tools/call":
        params = body.params or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return _rpc_error(body.id, -32601, f"Unknown tool: {name}")
        try:
            result = handler(arguments)
        except HTTPException as exc:
            return _rpc_result(body.id, {
                "content": [{"type": "text", "text": str(exc.detail)}],
                "isError": True,
            })
        except Exception as exc:  # noqa: BLE001 - surfaced to the agent, not swallowed
            return _rpc_result(body.id, {
                "content": [{"type": "text", "text": str(exc)}],
                "isError": True,
            })
        # FIX (2026-10-08): the result was returned only as a content item of
        # type "json", which is not a type the MCP specification defines, so a
        # spec client would drop it. The "json" item stays exactly as it was
        # (the Perfox agent was built against it), and the same data is also
        # sent as `structuredContent`, the spec's field for structured results.
        # Clients ignore keys they do not know, so neither side is affected by
        # the other's. The spec requires structuredContent to be an object, so
        # the list-shaped results (leads, bookings, availability) are wrapped.
        return _rpc_result(body.id, {
            "content": [{"type": "json", "json": result}],
            "structuredContent": result if isinstance(result, dict) else {"items": result},
            "isError": False,
        })

    return _rpc_error(body.id, -32601, f"Unknown method: {body.method}")
