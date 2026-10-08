"""
Inbound webhook for enquiries raised outside the dashboard.

The chat agent and the dashboard do not share a database. The agent (Perfox)
keeps its enquiries in its own backend, and `/api/crm/leads` - the route built
for it - has never been called by anything. Measured on 2026-09-21: a full
enquiry submission that the agent acknowledged produced no row here at all.

`/api/crm/leads` is not the thing to point a webhook at, though. It is a typed
agent API: it requires `lead_name`, calls the phone `phone_number`, and rejects
anything shaped differently. A webhook provider sends its own JSON - for this
form, the five fields the customer actually filled in (Full Name, Email Address,
Mobile Number, Subject, Message) - under whatever key names it likes, sometimes
wrapped in an envelope, sometimes as a list of {label, value} pairs. Pointing a
webhook at a strict endpoint means writing a field-mapping step somewhere, and
there is nowhere on the agent side to put one.

So this module accepts the message in whatever shape it arrives, works out which
field is the name and which is the phone, and files a proper lead. The only
thing left to do by hand is paste a URL into the agent's webhook setting.

Two details that are not obvious and are load-bearing:

  * Leads are written with origin = MANUAL. The loader's reset() deletes only
    origin = 'WORKBOOK' rows, so MANUAL survives a workbook re-upload. A chat
    lead written as WORKBOOK would be silently deleted by the next monthly
    import, which is the kind of bug only noticed a month later.

  * Webhooks retry. A provider that does not get a prompt 2xx sends the same
    enquiry again, so an endpoint that blindly inserts turns one enquiry into
    three. Deliveries are de-duplicated on identity within a short window.
"""

import hashlib
import os
import re
import secrets
import time
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request

from .db import is_db_ready, session
from etl import pii
from etl.dimensions import period_for, source_id_by_name

router = APIRouter(prefix="/api/webhooks", tags=["inbound-webhooks"])

# How long after a delivery an identical one is treated as that delivery
# arriving twice rather than as a second enquiry. Long enough to cover a
# provider's retry backoff, short enough that a customer who really does enquire
# twice in an afternoon gets two leads.
_RETRY_WINDOW = "10 minutes"

# Field names are matched with punctuation and case removed, so "Full Name",
# "full_name" and "fullName" are all the same key. Order matters only in that
# the first alias present wins.
_NAME = ("fullname", "name", "leadname", "customername", "contactname",
         "yourname", "firstname", "fullnames", "customer")
_EMAIL = ("email", "emailaddress", "emailid", "mail", "youremail")
_PHONE = ("mobile", "mobilenumber", "phone", "phonenumber", "contactnumber",
          "mobileno", "phoneno", "whatsapp", "whatsappnumber", "contact",
          "yourmobilenumber")
_SUBJECT = ("subject", "topic", "enquirysubject", "reason", "title")
_MESSAGE = ("message", "enquiry", "query", "comments", "comment", "notes",
            "details", "description", "howcanwehelpyou", "yourmessage",
            "messagebody", "body")
_MODEL = ("model", "modelofinterest", "car", "vehicle", "interestedin",
          "carmodel", "modelinterested")
_WHEN = ("createdat", "timestamp", "submittedat", "datetime", "occurredat",
         "eventtime", "date")


def _norm(key: Any) -> str:
    """Collapse "Full Name", "full_name" and "fullName" onto one key."""
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def _flatten(obj: Any, out: Optional[dict] = None, depth: int = 0) -> dict:
    """
    Reduce an arbitrary webhook body to one flat {normalised key: text} map.

    Providers wrap the payload differently - `{"data": {...}}`, `{"payload":
    {"fields": [...]}}`, or a bare object - and form builders in particular like
    to send a list of `{label, value}` pairs, where the field name arrives as a
    *value* rather than as a key. All three shapes have to land in the same
    place, because the caller cannot be asked to know which one it is sending.

    Shallow keys are filled first and deeper ones only fill gaps, so an envelope
    that repeats a field at the top level is not overridden by whatever is
    buried inside it.
    """
    out = {} if out is None else out
    if depth > 4:
        return out

    if isinstance(obj, dict):
        for k, v in obj.items():
            if not isinstance(v, (dict, list)) and v is not None and str(v).strip():
                out.setdefault(_norm(k), str(v).strip())

        # A {label: "Mobile Number", value: "98..."} pair is one field, not a
        # container - the label is the key actually wanted.
        label = next((obj[k] for k in obj
                      if _norm(k) in ("label", "name", "key", "field", "title")), None)
        value = next((obj[k] for k in obj
                      if _norm(k) in ("value", "answer", "text", "response")), None)
        if (label is not None and value is not None
                and not isinstance(value, (dict, list)) and str(value).strip()):
            out.setdefault(_norm(label), str(value).strip())

        for v in obj.values():
            if isinstance(v, (dict, list)):
                _flatten(v, out, depth + 1)

    elif isinstance(obj, list):
        for item in obj:
            _flatten(item, out, depth + 1)

    return out


def _pick(flat: dict, aliases: tuple) -> Optional[str]:
    for a in aliases:
        if flat.get(a):
            return flat[a]
    return None


def _clean_phone(raw: Optional[str]) -> Optional[str]:
    """
    Keep the ten digits that identify an Indian mobile.

    The same person writes +91 98765 43210, 098765 43210 and 9876543210, and the
    de-duplication below compares this value - so the formatting has to come off
    or a retry looks like a different customer.
    """
    if not raw:
        return None
    digits = re.sub(r"\D", "", str(raw))
    if len(digits) > 10:
        digits = digits[-10:]
    return digits or None


def _parse_when(raw: Optional[str]) -> Optional[datetime]:
    """A timestamp if the provider sent a readable one, otherwise None (= now)."""
    if not raw:
        return None
    text = str(raw).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).replace(tzinfo=None)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y %H:%M",
                "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


# PII POLICY (2026-10-08): retry detection without storing the phone number.
# A digest of the raw delivery, held in memory for the retry window only - it is
# never written to the database or a log, and it is gone on restart.
_RECENT: dict[str, tuple[int, float]] = {}
_RETRY_SECONDS = 600            # matches _RETRY_WINDOW


def _delivery_key(*parts) -> str:
    raw = "\x1f".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _recent_delivery(key: str) -> Optional[int]:
    now = time.time()
    for k in [k for k, (_, t) in _RECENT.items() if now - t > _RETRY_SECONDS]:
        _RECENT.pop(k, None)
    hit = _RECENT.get(key)
    return hit[0] if hit else None


def _remember_delivery(key: str, lead_id: int) -> None:
    _RECENT[key] = (lead_id, time.time())


def _check_secret(request: Request, x_webhook_secret: Optional[str],
                  authorization: Optional[str]) -> None:
    """
    Optional shared secret, accepted three ways.

    This route writes and is reachable from the internet, so it wants a secret -
    but webhook configuration screens vary in what they let you set. Some allow
    arbitrary headers, some offer nothing but a URL field. Supporting `?token=`
    as well means the endpoint can still be protected from such a screen.

    With WEBHOOK_SECRET unset the route is open, which is what makes it possible
    to paste the URL in and watch it work before deciding how to lock it down.
    """
    expected = os.environ.get("WEBHOOK_SECRET", "").strip()
    if not expected:
        return

    sent = (x_webhook_secret or "").strip()
    if not sent and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() == "bearer":
            sent = token.strip()
    if not sent:
        sent = (request.query_params.get("token") or "").strip()

    if not sent or not secrets.compare_digest(sent, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing webhook secret.")


def _target_period(cx, on_date):
    """
    Which reporting month the enquiry is filed under.

    By default the month the enquiry's own date falls in, which is the rule the
    rest of the system follows and the only one that keeps the numbers honest.

    That rule has a sharp edge for live enquiries: the dashboard shows exactly
    one active month, so an enquiry arriving today while the dashboard reports on
    an earlier month is stored correctly and displayed nowhere. Setting
    AGENT_LEAD_PERIOD=active files incoming enquiries into whichever month is on
    screen instead, so they appear as they arrive. It is off by default because
    it is a reporting choice, not a correctness fix.
    """
    mode = os.environ.get("AGENT_LEAD_PERIOD", "date").strip().lower()
    if mode == "active":
        row = cx.execute(
            "SELECT period_id, label FROM dim_period WHERE is_active"
        ).fetchone()
        if row is not None:
            pid = row["period_id"] if isinstance(row, dict) else row[0]
            label = row["label"] if isinstance(row, dict) else row[1]
            return pid, label, True
    return period_for(cx, on_date)


@router.get("/enquiry")
def describe_enquiry_webhook():
    """
    A readable answer to opening the webhook URL in a browser.

    Webhook setup screens - and the people using them - routinely GET the URL to
    check it is real before saving it. Returning 405 there reads as "broken", so
    this says what the endpoint is and what it expects instead.
    """
    return {
        "status": "ready",
        "endpoint": "POST /api/webhooks/enquiry",
        "purpose": "Receives enquiries from the chat agent and files them as leads.",
        "accepts": "Any JSON object. Field names are matched flexibly.",
        "recognised_fields": {
            "name": list(_NAME[:4]), "email": list(_EMAIL[:3]),
            "phone": list(_PHONE[:4]), "subject": list(_SUBJECT[:3]),
            "message": list(_MESSAGE[:4]),
        },
        "secured": bool(os.environ.get("WEBHOOK_SECRET", "").strip()),
        "period_rule": os.environ.get("AGENT_LEAD_PERIOD", "date").strip().lower(),
    }


@router.post("/enquiry")
async def receive_enquiry(
    request: Request,
    x_webhook_secret: Optional[str] = Header(None),
    authorization: Optional[str] = Header(None),
):
    """
    Accept one enquiry from the chat agent and file it as a lead.

    Deliberately forgiving about its input and strict about its output: anything
    carrying a recognisable name or phone number is accepted, and the reply says
    exactly where the lead landed and whether it is visible on the dashboard -
    because "success" on its own is what made the previous integration look like
    it was working while nothing was being displayed.
    """
    _check_secret(request, x_webhook_secret, authorization)

    if not is_db_ready():
        raise HTTPException(status_code=503, detail="Database not ready")

    try:
        body = await request.json()
    except Exception:
        # Some providers post form-encoded rather than JSON.
        try:
            body = dict(await request.form())
        except Exception:
            raise HTTPException(status_code=400,
                                detail="Body must be JSON or form-encoded.")

    flat = _flatten(body)
    name = _pick(flat, _NAME)
    phone = _clean_phone(_pick(flat, _PHONE))
    email = _pick(flat, _EMAIL)
    subject = _pick(flat, _SUBJECT)
    message = _pick(flat, _MESSAGE)
    model = _pick(flat, _MODEL)
    when = _parse_when(_pick(flat, _WHEN))

    # An enquiry with neither a name nor a way to call back is not a lead. 422
    # rather than 200, so a misconfigured mapping shows up in the provider's
    # delivery log instead of quietly filing blank rows.
    if not name and not phone:
        raise HTTPException(
            status_code=422,
            detail=("Could not find a name or phone number in the payload. "
                    f"Keys received: {sorted(flat)[:25]}"),
        )

    # PII POLICY (2026-10-08): the phone and email are read above only to
    # recognise the enquiry - from here on they exist only as [REDACTED], and a
    # phone or email the customer typed into the subject or message is cut out
    # of it (etl/pii.py). Nothing after this point sees the real values.
    #
    # The retry guard used to compare the stored mobile number. With no number
    # stored that comparison would treat every phone-only enquiry in a ten
    # minute window as one, so it now works in two layers instead:
    #   1. a fingerprint of the raw delivery, kept in this process's memory for
    #      the retry window and never written anywhere - an exact retry of the
    #      same delivery is caught here;
    #   2. after a restart, the stored name + (already scrubbed) message.
    delivery = _delivery_key(name, phone, email, subject, message)
    phone, email = pii.redact(phone), pii.redact(email)
    # Some forms put the number or the email in the name field too.
    name = pii.scrub_text(name)
    subject, message, model = (pii.scrub_text(subject), pii.scrub_text(message),
                               pii.scrub_text(model))

    note = " | ".join(p for p in (subject, message) if p) or None
    on = when or datetime.now()

    seen = _recent_delivery(delivery)
    if seen is not None:
        return {
            "status": "success", "duplicate": True, "lead_id": seen,
            "message": "Already received; treated as a retry of the same enquiry.",
        }

    try:
        with session() as cx:
            with cx.transaction():
                # Retry guard. Compared on loaded_at (when this arrived), not
                # created_at (when the enquiry happened), because a backdated
                # enquiry replayed twice is still one enquiry. Needs a name:
                # with no name and no stored phone there is nothing that tells
                # two enquiries apart, so those rely on the memory layer alone.
                dupe = cx.execute(
                    f"""
                    SELECT lead_id FROM lead
                     WHERE origin = 'MANUAL'
                       AND lead_name = %s
                       AND coalesce(enquiry_note, '') = coalesce(%s, '')
                       AND loaded_at > now() - interval '{_RETRY_WINDOW}'
                     ORDER BY lead_id DESC LIMIT 1
                    """,
                    (name, note),
                ).fetchone() if name else None
                if dupe is not None:
                    existing = dupe["lead_id"] if isinstance(dupe, dict) else dupe[0]
                    _remember_delivery(delivery, existing)
                    return {
                        "status": "success", "duplicate": True, "lead_id": existing,
                        "message": "Already received; treated as a retry of the "
                                   "same enquiry.",
                    }

                period_id, period_label, is_current = _target_period(cx, on.date())

                # FIX (2026-10-08): was a hard-coded source_id of 1, which means
                # whichever channel the first workbook load happened to create
                # first - not "chat". A chat enquiry is a DIGITAL lead, which is
                # also what db/triggers.sql files agent leads under; looked up
                # by name because surrogate ids differ between databases.
                digital = source_id_by_name(cx, "DIGITAL")

                row = cx.execute(
                    """
                    INSERT INTO lead (lead_name, mobile, email, source_id,
                                      model_of_interest, enquiry_note,
                                      lead_status, qualified_stage,
                                      created_at, period_id, is_current_period,
                                      origin, entered_by)
                    VALUES (%s, %s, %s, %s, %s, %s, 'New', 'New', %s, %s, %s,
                            'MANUAL', %s)
                    RETURNING lead_id
                    """,
                    (name, phone, email, digital, model, note, on, period_id,
                     is_current, "chat-agent"),
                ).fetchone()
                new_id = row["lead_id"] if isinstance(row, dict) else row[0]

        _remember_delivery(delivery, new_id)
        out = {
            "status": "success",
            "duplicate": False,
            "lead_id": new_id,
            "period": period_label,
            "in_active_period": is_current,
            "visible_on_dashboard": is_current,
            # What was STORED, so the agent's delivery log shows the redaction
            # rather than echoing the customer's number back out.
            "received": {"name": name, "phone": phone, "email": email,
                         "subject": subject, "message": message},
        }
        if not is_current:
            out["warning"] = (
                f"Stored correctly under {period_label}, but the dashboard is "
                f"reporting on a different month, so this lead is not on screen. "
                f"Activate {period_label}, or set AGENT_LEAD_PERIOD=active to "
                f"file incoming enquiries into the month being displayed."
            )
        return out

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
