"""
Lead tools for the Perfox sales agent (SOP 4: new car enquiry).

A small MCP server, separate from the dashboard's own MCP (app/mcp_server.py,
which only READS the dashboard for the "Dashboard Insights" agent). This one is
for the customer-facing sales agent and replaces its raw `execute_sql` access:
instead of writing SQL into the prompt and trusting the model to run only two
statements, the agent gets two fixed tools.

    create_lead        saves the enquiry in dsr.lead - the "simulated CRM" of
                       SOP 4 rule 7 - and returns the lead reference.
    get_hours_status   India time and whether sales / service / reception are
                       open - the START query of the persona prompt.

Left out for now, pending the manager's approval: Hot/Warm/Cold rating (SOP 4
rule 6) and the sales-team alert with its callback deadline (rule 7). The
rating column is simply not written, so it stays empty.

No authentication, by request. The only thing it can do is add a lead; it can
read nothing back, so there is no customer data to leak through it.

Run:   python mcp/leads_server.py            (serves http://127.0.0.1:8765/mcp)
Needs: DATABASE_URL, from the environment or the repo's .env.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import threading
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Annotated, Literal

import psycopg
from dotenv import load_dotenv
from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from psycopg_pool import ConnectionPool
from pydantic import Field

# The repo's .env, by explicit path: this file lives one folder down. A real
# environment variable wins over the file.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

log = logging.getLogger("leads_mcp")

DSN = os.environ.get("DATABASE_URL", "")
if DSN.startswith("postgres://"):
    DSN = "postgresql://" + DSN[len("postgres://"):]

# ---------------------------------------------------------------------------
# Hours. India has no daylight saving, so a fixed offset is exact and needs no
# tz database (which Windows does not ship).
# ---------------------------------------------------------------------------

IST = timezone(timedelta(hours=5, minutes=30))
SALES_OPEN, SALES_CLOSE = time(10, 15), time(18, 30)       # daily; reception too
SERVICE_OPEN, SERVICE_CLOSE = time(9, 0), time(18, 0)      # Monday to Saturday


def _now() -> datetime:
    return datetime.now(IST)


def sales_open(now: datetime) -> bool:
    return SALES_OPEN <= now.time() < SALES_CLOSE


def service_open(now: datetime) -> bool:
    return now.weekday() != 6 and SERVICE_OPEN <= now.time() < SERVICE_CLOSE


# ---------------------------------------------------------------------------
# The rules of SOP 4, as code instead of prompt text.
# ---------------------------------------------------------------------------

LeadType = Literal["test_drive", "service", "insurance", "rental", "career", "general_enquiry"]
Tag = Literal["FLEET", "FINANCE", "EXCHANGE", "INSURANCE", "ACCESSORIES", "BOOKING",
              "DELAYED", "CANCELLATION", "PAYMENT", "SERVICE", "COMPLAINT", "AFTER-HOURS"]

TYPE_TAG = {"insurance": "INSURANCE", "service": "SERVICE"}


def normalise_mobile(value: str | None) -> str:
    """A 10-digit Indian mobile from however it was typed or spoken, or ToolError."""
    digits = re.sub(r"\D", "", value or "")
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if not re.fullmatch(r"[6-9]\d{9}", digits):
        raise ToolError("The mobile number is not a valid 10-digit Indian mobile "
                        "(it starts with 6, 7, 8 or 9). Ask the caller to repeat it slowly.")
    return digits


def compose_note(tags: list[str], summary: str, best_time: str | None,
                 drive: str | None) -> str:
    """
    "[TAG][TAG] Best time to call: .... summary | Showroom test drive: Sat 11 AM".

    The database reads a test drive's day, time and place out of this text
    (dsr.test_drive_when): from the first "test drive" on, first date, first
    time of day. So the callback time goes BEFORE any "test drive" wording -
    "best time: 5 PM" after it would be booked as a 5 PM drive - and the drive
    is written in the shape that parser understands.
    """
    parts = [f"Best time to call: {best_time}."] if best_time else []
    parts.append(summary)
    if drive:
        parts.append(f"| {drive}")
    return ("".join(f"[{t}]" for t in tags) + " " + " ".join(parts)).strip()


# ---------------------------------------------------------------------------
# Database. Same settings as app/db.py, which was tuned against this pooler:
# the database is ~370 ms away, so what matters is round trips. autocommit makes
# the single INSERT one trip (it is atomic, triggers included), and
# prepare_threshold=None keeps statements unnamed, which the transaction
# pooler (port 6543) requires.
# ---------------------------------------------------------------------------

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()
_pii_checked = False


def _db() -> ConnectionPool:
    global _pool
    with _pool_lock:
        if _pool is None:
            _pool = ConnectionPool(
                DSN, min_size=1, max_size=4, max_idle=120.0,
                kwargs={"options": "-c search_path=dsr,public",
                        "prepare_threshold": None, "autocommit": True})
        return _pool


INSERT_LEAD = """
    INSERT INTO dsr.lead (lead_name, mobile, email, lead_type, model_of_interest,
                          variant_of_interest, colour_of_interest, lead_status,
                          dealership, entered_by, enquiry_note, test_drive_given,
                          trade_in, trade_in_vehicle, created_at)
    VALUES (%s, %s, %s, %s, %s, %s, %s, 'new', 'Elite Motors', 'AI Voice/Chat Agent',
            %s, false, %s, %s, now() AT TIME ZONE 'Asia/Kolkata')
    RETURNING lead_id
"""
# Everything else is the database's job: lead_fill_direct files the reporting
# month, channel and model (it keys on entered_by), and lead_pii_guard
# encrypts the phone / email and stores only the mask.


def _insert(params: tuple) -> int:
    global _pii_checked
    for attempt in (1, 2):
        try:
            with _db().connection() as cx:
                if not _pii_checked:
                    # Refuse a database that would store the full number readable
                    # (db/pii.sql not applied) - same guard as the dashboard's.
                    if not cx.execute("SELECT EXISTS (SELECT 1 FROM pg_constraint "
                                      "WHERE conname = 'lead_mobile_protected')").fetchone()[0]:
                        raise RuntimeError("db/pii.sql is not applied to this database")
                    _pii_checked = True
                return cx.execute(INSERT_LEAD, params).fetchone()[0]
        except psycopg.OperationalError:
            # A pooled connection the server dropped while idle: the pool discards
            # it, so one more try gets a fresh one. Losing a lead is worse than a
            # retry.
            if attempt == 2:
                raise


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

mcp = FastMCP(
    "elite-vw-leads",
    instructions="Lead capture for Elite Volkswagen Bengaluru's sales assistant.",
    mask_error_details=True,        # a failure never leaks SQL or the connection string
)


@mcp.tool
def get_hours_status() -> dict:
    """Current India time and whether sales, service and reception are open.
    Call once, silently, at the start of every conversation. Sales and reception
    10:15-18:30 daily; service 09:00-18:00 Monday to Saturday."""
    now = _now()
    return {
        "now_ist": now.strftime("%a %d %b %Y %H:%M"),
        "sales_open": sales_open(now),
        "reception_open": sales_open(now),
        "service_open": service_open(now),
    }


@mcp.tool
def create_lead(
    name: Annotated[str, Field(description="Customer's name, spelled as confirmed.", max_length=100)],
    summary: Annotated[str, Field(max_length=600, description=(
        "One or two short sentences: what the customer wants, plus budget, loan or cash, "
        "personal or company lease, when they plan to buy, and anything else they said. "
        "For FLEET add company, contact person and role, number of cars, city. Never a "
        "street address, phone number or email."))],
    mobile: Annotated[str | None, Field(description=(
        "10-digit mobile the customer confirmed. Leave it out when they confirmed the "
        "number they are calling or chatting from - it is then taken from the call."))] = None,
    email: Annotated[str | None, Field(description="Email, only if offered (always ask for FLEET).", max_length=120)] = None,
    lead_type: Annotated[LeadType, Field(description=(
        "test_drive, service, insurance, rental, career, or general_enquiry for everything else."))] = "general_enquiry",
    model: Annotated[str | None, Field(description="Model of interest, as in the product files.", max_length=60)] = None,
    variant: Annotated[str | None, Field(max_length=60)] = None,
    colour: Annotated[str | None, Field(max_length=40)] = None,
    tags: Annotated[list[Tag] | None, Field(description=(
        "Every tag that applies. EXCHANGE, INSURANCE, SERVICE and AFTER-HOURS are added automatically."))] = None,
    trade_in_vehicle: Annotated[str | None, Field(max_length=200, description=(
        "Exchange only: old car make, model, year, km, owners, city. Never a value."))] = None,
    drive_when: Annotated[str | None, Field(max_length=120, description=(
        "test_drive only: the preferred day and time, first choice first, then the second option. "
        "E.g. 'Saturday 11 AM, second option Sunday 3 PM'."))] = None,
    drive_place: Annotated[Literal["showroom", "home"], Field(description="test_drive only.")] = "showroom",
    best_time: Annotated[str | None, Field(max_length=80, description="Best time to reach the customer.")] = None,
) -> dict:
    """Save a customer enquiry as a lead. Call it ONCE per customer need, only after the
    customer has confirmed their name and number.

    Returns lead_id; read it to the customer digit by digit, from lead_id_spoken.

    If it returns an error, the lead was NOT saved: say it is noted, hand off to the board."""
    now = _now()
    mobile = normalise_mobile(mobile or get_http_headers().get("x-sa-end-user-phone"))
    name = " ".join(name.split())
    if not name:
        raise ToolError("The name is empty. Ask the caller for their name.")
    email = (email or "").strip() or None
    if email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ToolError("The email address looks wrong. Ask the caller to spell it again.")

    # Tags: the agent's, plus the ones the facts already imply. dict keeps order, drops repeats.
    given = list(dict.fromkeys(tags or []))
    if lead_type in TYPE_TAG:
        given.append(TYPE_TAG[lead_type])
    if trade_in_vehicle:
        given.append("EXCHANGE")
    if not (service_open(now) if lead_type == "service" else sales_open(now)):
        given.append("AFTER-HOURS")
    all_tags = list(dict.fromkeys(given))

    drive = f"{drive_place.title()} test drive: {drive_when or 'requested'}" if lead_type == "test_drive" else None
    note = compose_note(all_tags, summary.strip(), best_time, drive)

    try:
        lead_id = _insert((name, mobile, email, lead_type, model, variant, colour,
                           note, bool(trade_in_vehicle), trade_in_vehicle))
    except Exception:
        log.exception("lead insert failed")
        raise ToolError("The lead could not be saved. Tell the caller it is noted and "
                        "give the board number.") from None
    log.info("lead %s saved (%s)", lead_id, lead_type)
    return {"lead_id": lead_id, "lead_id_spoken": " ".join(str(lead_id))}


if __name__ == "__main__":
    if not DSN:
        sys.exit("DATABASE_URL is not set (environment or the repo's .env).")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    # HOST: 127.0.0.1 only accepts local requests; use 0.0.0.0 behind a tunnel or on a host.
    mcp.run(transport="http", show_banner=False,
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("MCP_PORT") or os.environ.get("PORT") or 8765),
            path="/mcp", stateless_http=True, json_response=True)
