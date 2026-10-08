import os
import re
import secrets
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, field_validator
from typing import Optional

from .db import is_db_ready, fetch_all, session
from etl import pii
from etl.dimensions import period_for, source_id_by_name


def require_agent_key(
    x_api_key: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
) -> None:
    """
    Shared-secret guard for the agent surface.

    These routes exist to be called from outside this machine, which means that
    the moment the app is reachable from the internet they are too - and one of
    them writes. Set AGENT_API_KEY and every /api/crm route then needs it, sent
    as `X-API-Key: <key>` or `Authorization: Bearer <key>`.

    With AGENT_API_KEY unset the routes stay open, so nothing changes for a
    loopback-only dev server. That default is only safe while the API is bound
    to 127.0.0.1 - set the key before putting a tunnel in front of it.

    compare_digest rather than ==, so a wrong key cannot be recovered by timing
    how long the rejection takes.
    """
    expected = os.environ.get("AGENT_API_KEY", "").strip()
    if not expected:
        return

    sent = (x_api_key or "").strip()
    if not sent and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            sent = token.strip()

    if not sent or not secrets.compare_digest(sent, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key.")


router = APIRouter(prefix="/api/crm", tags=["agent-integration"],
                   dependencies=[Depends(require_agent_key)])

class NewLeadPayload(BaseModel):
    lead_name: str
    phone_number: Optional[str] = None
    # FIX (2026-10-08): defaulted to 1, i.e. whichever channel the first
    # workbook load created first. Omitted now means DIGITAL, looked up by name
    # in create_lead() below - the same channel db/triggers.sql gives agent leads.
    source_id: Optional[int] = None
    consultant_id: Optional[int] = None
    model_id: Optional[int] = None
    variant_of_interest: Optional[str] = None
    origin: Optional[str] = "MANUAL"
    # When the enquiry actually came in. The agent normally omits it and means
    # "now", but a conversation logged after the fact should be filed under the
    # day it happened, not the day it was typed up.
    created_at: Optional[datetime] = None
    email: Optional[str] = None
    lead_type: Optional[str] = None
    model_of_interest: Optional[str] = None
    rating: Optional[str] = None

    # PII POLICY (2026-10-08): the agent may still send the customer's phone
    # and email - it is not an error to - but neither is stored. Replaced here,
    # before the route ever sees them (etl/pii.py).
    @field_validator("phone_number", "email")
    @classmethod
    def _no_pii(cls, v):
        return pii.redact(v)

    # A phone or email inside the name field is cut out; the name is kept.
    @field_validator("lead_name")
    @classmethod
    def _name(cls, v):
        return pii.scrub_text(v)

class FetchLeadsPayload(BaseModel):
    limit: Optional[int] = 50
    status: Optional[str] = 'New'
    # Which reporting month to read. 'active' is the one the dashboard is
    # showing; a label like 'AUG2026' reads that month; 'all' drops the filter.
    period: Optional[str] = 'active'
    # Name, for answering "what do we have for <customer>". (PII POLICY
    # 2026-10-08: this also matched the mobile number; phone numbers are no
    # longer stored, so it matches the name only.)
    search: Optional[str] = None
    # A day or a span of days: 'today', 'yesterday' or YYYY-MM-DD. Given
    # either, the reporting month is not consulted - today's enquiries are
    # today's, whichever month the dashboard is set to.
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    # Hot, Warm or Cold: the lead's rating, or for a lead with none (the
    # AI agent's), the tag in its note - "[HOT] Test drive | ...".
    rating: Optional[str] = None


class FetchBookingsPayload(BaseModel):
    limit: Optional[int] = 50
    period: Optional[str] = 'active'
    search: Optional[str] = None
    status: Optional[str] = None          # fulfilment_status
    date_from: Optional[str] = None       # as for leads, on the booking date
    date_to: Optional[str] = None


# India's calendar: "today" for the showroom, whatever the server's clock says.
_IST = timezone(timedelta(hours=5, minutes=30))


def _day(value: Optional[str]) -> Optional[date]:
    """'today', 'yesterday', 'tomorrow' or YYYY-MM-DD, as a date in India."""
    if not value or not value.strip():
        return None
    v = value.strip().lower()
    shift = {"today": 0, "yesterday": -1, "tomorrow": 1}
    if v in shift:
        return datetime.now(_IST).date() + timedelta(days=shift[v])
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(status_code=400,
                            detail=f"Not a day: {value!r}. Use today, yesterday, tomorrow, YYYY-MM-DD, "
                                   f"or a span such as this week, last 7 days or last month.")


def span(value: Optional[str]) -> Optional[tuple[date, date]]:
    """Days named in words - 'this week', 'last week', 'next week', 'last 7
    days', 'next 30 days', 'this month', 'last month', 'next month' - as the
    first and last day, in India; None when the words are not one of those.
    A chat model asked about "this week" says "this week": working the dates
    out itself is where it goes wrong. A week runs Monday to Sunday."""
    if not value or not value.strip():
        return None
    v = re.sub(r"\s+", " ", value.strip().lower())
    today = datetime.now(_IST).date()
    monday = today - timedelta(days=today.weekday())
    if v in ("this week", "current week"):
        return monday, monday + timedelta(days=6)
    if v in ("last week", "previous week"):
        return monday - timedelta(days=7), monday - timedelta(days=1)
    if v in ("next week", "coming week"):
        return monday + timedelta(days=7), monday + timedelta(days=13)
    m = re.fullmatch(r"(last|past|next|coming) (\d{1,3}) days?", v)
    if m:
        n = max(1, int(m.group(2)))
        if m.group(1) in ("last", "past"):
            return today - timedelta(days=n - 1), today
        return today, today + timedelta(days=n - 1)
    first = today.replace(day=1)
    if v in ("this month", "current month"):
        start = first
    elif v in ("last month", "previous month"):
        start = (first - timedelta(days=1)).replace(day=1)
    elif v in ("next month", "coming month"):
        start = (first + timedelta(days=32)).replace(day=1)
    else:
        return None
    return start, (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)


# A booking's fulfilment status in the words people use. The column is an
# enum spelled BOOKED / NO_STOCK / ALLOTED / RETAILED / CANCELLED, and
# 'booked' used to reach it as is - a database error, not an answer.
_BOOKING_STATUSES = {
    "booked": "BOOKED", "open": "BOOKED",
    "no stock": "NO_STOCK", "nostock": "NO_STOCK", "backorder": "NO_STOCK", "backorders": "NO_STOCK",
    "back order": "NO_STOCK", "back orders": "NO_STOCK",
    "alloted": "ALLOTED", "allotted": "ALLOTED", "allotment": "ALLOTED",
    "retailed": "RETAILED", "retail": "RETAILED", "retails": "RETAILED", "delivered": "RETAILED",
    "cancelled": "CANCELLED", "canceled": "CANCELLED", "cancel": "CANCELLED", "cancellation": "CANCELLED",
}


def booking_status(value: Optional[str]) -> Optional[str]:
    """The enum value for a status as written, or None for no filter."""
    if not value or not value.strip() or value.strip().lower() in ("all", "any"):
        return None
    v = re.sub(r"[\s_-]+", " ", value.strip().lower())
    if v in _BOOKING_STATUSES:
        return _BOOKING_STATUSES[v]
    raise HTTPException(status_code=400, detail=(
        f"Not a booking status: {value!r}. Use booked, no_stock (backorder), allotted, retailed or cancelled."))


def _date_clause(column: str, date_from: Optional[str],
                 date_to: Optional[str]) -> Optional[tuple[str, list]]:
    """A day or a span of days on `column`, or None when neither end is given.
    One end alone is that single day; a span in words ('this week') is its
    days."""
    a, b = span(date_from), span(date_to)
    lo = a[0] if a else _day(date_from)
    hi = b[1] if b else (a[1] if a and (not date_to or date_to == date_from) else _day(date_to))
    if lo is None and hi is None:
        return None
    lo, hi = lo or hi, hi or lo
    if hi < lo:
        lo, hi = hi, lo
    return f" AND {column} BETWEEN %s AND %s", [lo, hi]


def _period_clause(period: Optional[str], alias: str,
                   id_expr: str | None = None) -> tuple[str, list]:
    """
    Turn a period argument into SQL. Defaults to the month the dashboard is
    reporting on, because an agent asking "what leads do we have" means now -
    not the entire history of the table.

    `id_expr` is the expression giving a row's period_id. It defaults to the
    obvious column, but v_bookings does not carry period_id, so that caller
    passes a lookup against the base table. Matching on the stored period rather
    than on the row's DATE is deliberate: a workbook loaded into one month can
    carry dates from another, and the month it was filed under is the answer.
    """
    want = (period or 'active').strip()
    if want.lower() == 'all':
        return "", []
    if want.lower() == 'active':
        return f" AND {alias}.is_current_period", []
    return (f" AND {id_expr or f'{alias}.period_id'} = "
            f"(SELECT period_id FROM dim_period WHERE upper(label) = upper(%s))"), [want]


@router.post("/fetch-leads")
def fetch_leads_for_agent(payload: FetchLeadsPayload):
    """
    POST API specifically for Perfox inbound/outbound agents to pull leads.

    Two things used to make this return the wrong data entirely.

    It had no period filter, so it read the whole table - including the 1,815
    row historical CRM dump from 2024 that is kept for year-on-year comparison.
    An agent asking for this month's leads got records from July 2024.

    And it matched `lead_status = 'New'` on a column that is NULL for every row
    the dashboard or a workbook ever wrote; only the 2024 dump carries a status
    at all. `NULL = 'New'` is never true in SQL, so the filter could not return
    anything BUT the 2024 archive. A lead entered on the dashboard five minutes
    ago was invisible, while a lead from 2024 came back fine.

    So: the status match is NULL-safe (an untouched lead IS new), and the read
    is scoped to a reporting month, defaulting to the one on screen.

    The match is also blind to case: the AI agent saves its leads as 'new',
    a workbook as 'New', and 'New' alone used to skip every lead the agent
    took. A day or a span of days (date_from / date_to) reads those days,
    whichever month the dashboard is set to; status 'all' drops that filter.
    """
    if not is_db_ready():
        raise HTTPException(status_code=503, detail="Database not ready")
    dated = _date_clause("l.created_at::date", payload.date_from, payload.date_to)

    try:
        sql = """
            SELECT l.lead_id, l.lead_name, l.mobile, l.email,
                   l.source_id, s.name AS source,
                   l.consultant_id, c.display_name AS consultant,
                   l.model_id, m.name AS model, l.variant_of_interest,
                   COALESCE(l.lead_status, 'New') AS lead_status,
                   l.qualified_stage, l.rating, l.created_at,
                   l.model_of_interest, l.lead_type, l.enquiry_note,
                   p.label AS period
            FROM lead l
            LEFT JOIN dim_period      p ON p.period_id     = l.period_id
            LEFT JOIN dim_lead_source s ON s.source_id     = l.source_id
            LEFT JOIN dim_consultant  c ON c.consultant_id = l.consultant_id
            LEFT JOIN dim_model       m ON m.model_id      = l.model_id
            WHERE TRUE
        """
        params: list = []

        if payload.status and payload.status.strip().lower() != 'all':
            # COALESCE, so a lead nobody has touched counts as New instead of
            # falling out of every filter.
            sql += " AND lower(COALESCE(l.lead_status, 'New')) = lower(%s)"
            params.append(payload.status.strip())

        if payload.rating and payload.rating.strip():
            # "HOT]" also finds the agent's "[SALES-HOT]".
            sql += " AND (lower(l.rating) = lower(%s) OR (l.rating IS NULL AND l.enquiry_note ILIKE %s))"
            params += [payload.rating.strip(), f"%{payload.rating.strip().upper()}]%"]

        if dated:
            sql += dated[0]
            params += dated[1]
        else:
            clause, extra = _period_clause(payload.period, "l")
            sql += clause
            params += extra

        if payload.search:
            # PII POLICY (2026-10-08): name only - mobile holds [REDACTED].
            sql += " AND l.lead_name ILIKE %s"
            params.append(f"%{payload.search.strip()}%")

        sql += " ORDER BY l.created_at DESC NULLS LAST LIMIT %s"
        params.append(payload.limit)

        return fetch_all(sql, tuple(params))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/fetch-bookings")
def fetch_bookings_for_agent(payload: FetchBookingsPayload):
    """
    Bookings, for an agent asked about a customer's order.

    There was no booking endpoint at all, so any question about an order - "what
    is booked for <customer>", "has their car been allotted" - could only be
    answered by guessing. Reads v_bookings, which is the same view the
    dashboard's order book draws, so the two cannot disagree. A day or a span
    of days (date_from / date_to, on the booking date) reads those days,
    whichever month the dashboard is set to.
    """
    if not is_db_ready():
        raise HTTPException(status_code=503, detail="Database not ready")
    dated = _date_clause("b.booking_date::date", payload.date_from, payload.date_to)
    status = booking_status(payload.status)

    try:
        sql = """
            SELECT b.booking_id, b.booking_date, b.customer_name, b.mobile,
                   b.consultant, b.model, b.variant, b.colour,
                   b.fulfilment_status, b.booking_amount, b.ageing_days,
                   b.allotted_chassis, b.source, b.crm_entry_done
            FROM v_bookings b
            WHERE TRUE
        """
        params: list = []

        if dated:
            sql += dated[0]
            params += dated[1]
        else:
            clause, extra = _period_clause(
                payload.period, "b",
                id_expr="(SELECT bb.period_id FROM booking bb "
                        "WHERE bb.booking_id = b.booking_id)")
            sql += clause
            params += extra

        if status:
            sql += " AND b.fulfilment_status::text = %s"
            params.append(status)

        if payload.search:
            # PII POLICY (2026-10-08): name only - mobile holds [REDACTED].
            sql += " AND b.customer_name ILIKE %s"
            params.append(f"%{payload.search.strip()}%")

        sql += " ORDER BY b.booking_date DESC NULLS LAST LIMIT %s"
        params.append(payload.limit)

        return fetch_all(sql, tuple(params))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/leads")
def create_lead(lead: NewLeadPayload):
    """
    POST API for Perfox inbound/outbound agents to push a new lead into the CRM.

    The lead is filed against a reporting month, which is what makes it visible.
    This used to insert seven columns and leave period_id, is_current_period and
    created_at unset, so an agent's lead landed in the table belonging to no
    month at all - and since every dashboard view is scoped
    `WHERE is_current_period`, it was counted by nothing and appeared nowhere.
    The agent got "success" and the dashboard never moved.

    period_for() is the same helper the dashboard's own entry form uses, so both
    ways in now agree: the month comes from the enquiry's DATE, and the month is
    created if this is the first record for it. A lead is never forced into
    whichever month the dashboard happens to be showing - that would file
    September enquiries under August.

    `in_active_period` in the reply says whether this lead lands in the month the
    dashboard is currently reporting on. False is not an error: the lead is
    stored and correct, it just belongs to a month nobody is looking at yet.

    The insert itself fires the lead_notify trigger, so every open dashboard is
    pushed an update over SSE the moment the transaction commits. Nothing polls.
    """
    if not is_db_ready():
        raise HTTPException(status_code=503, detail="Database not ready")

    try:
        with session() as cx:
            # One transaction: creating the month and filing the lead against it
            # must not be separable, or a crash between them leaves an empty
            # month behind.
            with cx.transaction():
                on = lead.created_at or datetime.now()
                on_date = on.date() if isinstance(on, datetime) else on
                period_id, period_label, is_current = period_for(cx, on_date)

                cur = cx.execute("""
                    INSERT INTO lead (lead_name, mobile, email, source_id,
                                      consultant_id, model_id, lead_type,
                                      model_of_interest, variant_of_interest,
                                      rating, lead_status, qualified_stage,
                                      created_at, period_id, is_current_period,
                                      origin)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            'New', 'New', %s, %s, %s, %s)
                    RETURNING lead_id
                """, (
                    lead.lead_name,
                    # The payload has always called this phone_number while the
                    # column is `mobile`; the value used to be accepted and then
                    # silently dropped. (Already [REDACTED] by the payload
                    # validator above - PII policy 2026-10-08.)
                    lead.phone_number,
                    lead.email,
                    lead.source_id if lead.source_id is not None
                    else source_id_by_name(cx, "DIGITAL"),
                    lead.consultant_id, lead.model_id,
                    lead.lead_type, lead.model_of_interest,
                    lead.variant_of_interest, lead.rating,
                    on, period_id, is_current, lead.origin,
                ))
                row = cur.fetchone()
                new_id = row["lead_id"] if isinstance(row, dict) else row[0]

        return {
            "status": "success",
            "lead_id": new_id,
            "message": "Lead created successfully",
            # Added, not swapped: the three keys above are what the agent
            # already reads.
            "period": period_label,
            "in_active_period": is_current,
            "created_at": on.isoformat(),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
