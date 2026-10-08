"""
Test drives - the showroom's test drives, and nothing else.

Every test drive lives in dsr.test_drive_booking (db/test_drives.sql), and
this section reads nothing else: no car bookings, no general enquiries.

  Enquiries  test drives asked for and still waiting for a time (status
             'requested'). The database files one from every test-drive
             enquiry the AI agent or the website saves.
  Bookings   test drives with their slot - booked, attended, no-show,
             cancelled - booked by the AI agent on the call
             (dsr.book_test_drive), by the sales desk, or for a walk-in.
  Samples    made-up drives (sample = true) that
             fill the calendar for showing it. They hold no slot.

Read, never written: the cars (dim_model, dim_variant), the sales executives
(dim_consultant), and the AI agent's call log, for test drives promised on a
call with nothing on record.

One demo car per model family is assumed: the database records stock but not
which cars are demonstrators, so a family is what a test drive is booked on.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta, timezone
from typing import Literal, Optional

import psycopg
from fastapi import APIRouter, HTTPException, Path as PathParam, Query
from pydantic import BaseModel, Field, field_validator

from .db import session
from etl import pii

# Its own prefix, deliberately. /api/test-drives already belongs to the Record
# drawer (entry.py), whose POST writes a completed drive to the test_drive log.
router = APIRouter(prefix="/api/test-drive-board", tags=["test drives"])

SLOT_START, SLOT_END, SLOT_MINUTES = "09:30", "19:00", 30

# The showroom's clock. India keeps no daylight saving, so a fixed offset is
# exact - and needs no time-zone database, which Windows does not ship.
_IST = timezone(timedelta(hours=5, minutes=30))

_TEST_DRIVE = re.compile(r"test.?drive", re.I)
_WHEN = re.compile(
    r"\b(today|tomorrow|this weekend|next week|monday|tuesday|wednesday|thursday|"
    r"friday|saturday|sunday|\d{1,2}(?::\d{2})?\s*(?:am|pm))\b", re.I)
_GEARBOX = re.compile(r"\b(DSG|AT|MT)\b", re.I)
# The DSR's trim shorthand, written out where a variant has no longer name.
_TRIM = {"CL": "Comfortline", "HL": "Highline"}


def _now() -> datetime:
    return datetime.now(_IST)


def _slots() -> list[str]:
    t = datetime.strptime(SLOT_START, "%H:%M")
    end = datetime.strptime(SLOT_END, "%H:%M")
    out = []
    while t < end:
        out.append(t.strftime("%H:%M"))
        t += timedelta(minutes=SLOT_MINUTES)
    return out


_SLOTS = _slots()


# ------------------------------------------------------------ the drives

_DRIVE_COLS = """booking_id, car_id, td_date, start_time, asked_time, customer, phone, consultant,
                 location, address, source, status, call_id, lead_id, note, created_at, updated_at"""

# Whether db/test_drives.sql has added the sample flag yet. Until it has there
# are no samples - every drive is real - and the section must still load, so
# nothing here names the column without asking first. Once there, it stays.
_has_samples = False


def _samples_on(cx) -> bool:
    global _has_samples
    if not _has_samples:
        _has_samples = cx.execute("""
            SELECT EXISTS (SELECT 1 FROM information_schema.columns
                            WHERE table_schema = 'dsr' AND table_name = 'test_drive_booking'
                              AND column_name = 'sample') AS e""").fetchone()["e"]
    return _has_samples


def _cols(cx) -> str:
    return _DRIVE_COLS + (", sample" if _samples_on(cx) else ", false AS sample")


def _real(cx) -> str:
    """The filter that leaves the samples out."""
    return " AND NOT sample" if _samples_on(cx) else ""


# An enquiry whose day has gone by with no booking is marked a no-show by the
# database (dsr.lapse_test_drive_enquiries, db/test_drives.sql). The board
# asks for it as it reads - at most once a minute - so what it shows is
# current. Until that SQL has been run the function is not there, and the
# board reads on without it.
_lapsed_at = 0.0


def _lapse(cx) -> None:
    global _lapsed_at
    if time.monotonic() - _lapsed_at < 60:
        return
    _lapsed_at = time.monotonic()
    try:
        cx.execute("SELECT dsr.lapse_test_drive_enquiries()")
    except psycopg.errors.UndefinedFunction:
        pass


def _drive(r) -> dict:
    return {
        "id": r["booking_id"],
        "car_id": r["car_id"],
        "date": r["td_date"].isoformat() if r["td_date"] else None,     # an enquiry may have no day yet
        "start": r["start_time"],                                       # nor a slot
        "asked_time": r["asked_time"],
        "customer": r["customer"],
        "phone": r["phone"] or "",
        "consultant": r["consultant"] or "",
        "location": r["location"],
        "address": r["address"] or "",
        "source": r["source"],
        "status": r["status"],
        "call_id": r["call_id"],
        "from_enquiry": r["lead_id"] is not None,
        "note": r["note"] or "",
        "sample": r["sample"],
        "enquired_on": r["enquired_on"].isoformat(),
        # The day the calendar shows it on: its own day, or - an enquiry that
        # names no day yet - the day it came in. Every enquiry has a place.
        "on": r["on_day"].isoformat(),
        "created_at": r["created_at"].astimezone(_IST).isoformat(timespec="seconds"),
        "updated_at": r["updated_at"].astimezone(_IST).isoformat(timespec="seconds"),
    }


# The day an enquiry came in: its lead's day when it came from one (the
# agent's call, the website, the Record drawer), else the day it was filed.
# A lead's created_at is India's wall-clock time already.
_ENQUIRED = """coalesce((SELECT l.created_at::date FROM dsr.lead l WHERE l.lead_id = b.lead_id),
                        (b.created_at AT TIME ZONE 'Asia/Kolkata')::date)"""


def _drives(cx, where: str = "TRUE", params: tuple | dict = (), samples: bool = True) -> list[dict]:
    # `where` is a fixed string from this module; values travel in `params`.
    # It may use on_day, the day the calendar shows a drive on.
    keep = "" if samples else _real(cx)
    return [_drive(r) for r in cx.execute(
        f"""SELECT * FROM (SELECT {_cols(cx)}, {_ENQUIRED} AS enquired_on,
                                  coalesce(b.td_date, {_ENQUIRED}) AS on_day
                             FROM dsr.test_drive_booking b) d
             WHERE ({where}){keep}
             ORDER BY td_date NULLS LAST, start_time NULLS LAST, created_at""", params).fetchall()]


# ---------------------------------------------------------------- the cars

def _slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", family.lower()).strip("-")


def _title(s: str) -> str:
    """'TIGUAN R-LINE' -> 'Tiguan R-Line'. Short, numbered and bracketed tokens
    are codes and keep their capitals: GTI, TSI, 1.5, (FL)."""
    def word(w: str) -> str:
        if len(w) <= 3 or re.search(r"[()\d]", w):
            return w.upper()
        return w[:1].upper() + w[1:].lower()
    return " ".join("-".join(word(p) for p in w.split("-")) for w in s.split())


def _variant_label(model: str, family: str, name: str | None, text: str | None) -> str:
    """The catalogue's description less the model it is listed under, so
    'TAIGUN 1.0L TSI 85kW AT Topline' under Taigun reads '1.0L TSI 85kW AT
    Topline'. With no description, the DSR's short name with its trim shorthand
    written out: 'CL MT' reads 'Comfortline MT'."""
    t = (text or "").strip()
    if t:
        for prefix in (model, family):
            if t.upper().startswith(prefix.upper() + " "):
                return t[len(prefix):].strip()
        return t
    words = [_TRIM.get(w.upper(), w) for w in (name or "").split()]
    return _title(" ".join(words)) if words else ""


# Trim names as the catalogue spells them, longest first: "GT PLUS SPORT"
# must win over "GT PLUS", and "GT PLUS" over a bare "SPORT".
_TRIM_WORDS = (("GT PLUS SPORT", "GT Plus Sport"), ("GT PLUS", "GT Plus"), ("GT LINE", "GT Line"),
               ("TOPLINE", "Topline"), ("HIGHLINE", "Highline"), ("COMFORTLINE", "Comfortline"),
               ("CHROME", "Chrome"), ("SPORT", "Sport"))


def trim_of(name: str | None, text: str | None) -> tuple[str, str | None, str | None]:
    """A variant as (trim, gearbox, engine), however the catalogue spells it:
    'HL MT' and 'TAIGUN 1.0L TSI 85kW MT Highline' are one trim. The 1.5 DSG
    with no trim word is the GT Plus."""
    t = f" {(text or '').upper()} {(name or '').upper()} "
    t = re.sub(r"\bHL\b", "HIGHLINE", re.sub(r"\bCL\b", "COMFORTLINE", t))
    trim = next((label for word, label in _TRIM_WORDS if word in t), None)
    if "1.5" in t and trim in (None, "Sport"):
        trim = "GT Plus Sport" if trim == "Sport" else "GT Plus"
    gear = _GEARBOX.search(t)
    engine = "1.5 TSI" if "1.5" in t else "1.0 TSI" if ("1.0" in t or "85KW" in t.replace(" ", "")) else None
    return trim or _title((name or "").strip()), gear.group(1).upper() if gear else None, engine


def distinct_trims(variants: list[tuple[str | None, str | None]]) -> list[str]:
    """The trims a set of variants comes to, each once. Taigun and the Taigun
    facelift list the same trims, and the catalogue spells some twice ('1.0
    TSI COMFORTLINE' is 'CL MT'): counted as rows, the Taigun was 20 variants;
    it is 10 trims. A trim named with no gearbox is one of its geared kind
    when the catalogue has one."""
    seen: dict[tuple[str, str | None], str | None] = {}
    described: set[tuple[str, str | None]] = set()
    words: set[str] = set()
    for name, text in variants:
        trim, gear, engine = trim_of(name, text)
        seen[(trim, gear)] = seen.get((trim, gear)) or engine
        if text:
            described.add((trim, gear))
        words |= set(re.findall(r"[A-Z0-9.]+", f"{text or ''} {name or ''}".upper()))
    geared = {trim for trim, gear in seen if gear}

    def short_form(trim: str, gear: str | None) -> bool:
        # A bare name with no description that starts a longer word the
        # family uses - 'GT' of 'GOLF GTI' - is a short form, not a trim.
        if gear or (trim, gear) in described:
            return False
        return any(w != trim.upper() and w.startswith(trim.upper()) for w in words)

    keep = [(t, g) for t, g in seen if (g or t not in geared) and not short_form(t, g)]
    return sorted(" ".join(x for x in (seen[(t, g)], t, g) if x) for t, g in keep)


_cars_cache: tuple[float, list[dict]] | None = None
_CARS_TTL = 300               # the catalogue changes with a workbook, not by the minute


def _cars() -> list[dict]:
    """The line-up, from the catalogue: one entry per model family, busiest
    first, with the variants listed under each of its models.

    The board used to carry three placeholder cars. The catalogue holds six
    models in five families and thirty-three variants, and every enquiry and
    booking names one of them, so that is the fleet the board draws. Kept for a
    few minutes, since every board load and every booking asks for it."""
    global _cars_cache
    if _cars_cache and time.monotonic() - _cars_cache[0] < _CARS_TTL:
        return _cars_cache[1]
    with session() as cx:
        rows = cx.execute("""
            SELECT m.family, m.name AS model, m.is_cbu,
                   v.variant_id, v.name AS variant, v.long_model_text, v.transmission
              FROM dim_model m
              LEFT JOIN dim_variant v ON v.model_id = m.model_id
             ORDER BY m.family, m.name, v.long_model_text NULLS LAST, v.name
        """).fetchall()
        # Busiest first, by everything on record against the family: its
        # enquiries, its bookings and its stock.
        busy = {r["family"]: r["n"] for r in cx.execute("""
            SELECT m.family, count(*) AS n
              FROM (SELECT model_id FROM lead    WHERE period_id IS NOT NULL
                    UNION ALL
                    SELECT model_id FROM booking WHERE period_id IS NOT NULL
                    UNION ALL
                    SELECT model_id FROM vehicle) x
              JOIN dim_model m ON m.model_id = x.model_id
             GROUP BY m.family
        """).fetchall()}

    families: dict[str, dict] = {}
    for r in rows:
        fam = families.setdefault(r["family"], {"imported": False, "models": {}, "raw": []})
        fam["imported"] = fam["imported"] or bool(r["is_cbu"])
        model = fam["models"].setdefault(r["model"], {
            "name": _title(r["model"]), "imported": bool(r["is_cbu"]), "variants": []})
        if r["variant_id"] is None:
            continue
        fam["raw"].append((r["variant"], r["long_model_text"]))
        gear = _GEARBOX.search(f"{r['long_model_text'] or ''} {r['variant'] or ''}")
        model["variants"].append({
            "id": r["variant_id"],
            "name": _variant_label(r["model"], r["family"], r["variant"], r["long_model_text"]),
            "gearbox": (r["transmission"] or (gear.group(1) if gear else "")).upper(),
        })

    cars = []
    for family, fam in families.items():
        models = list(fam["models"].values())
        variants = [v for m in models for v in m["variants"]]
        gearboxes = [g for g in ("MT", "AT", "DSG") if any(v["gearbox"] == g for v in variants)]
        # Short enough for the board's car column; the gearboxes go with the
        # full variant list on the Cars tab.
        trims = distinct_trims(fam["raw"])
        bits = (["Imported"] if fam["imported"] else []) + (
            [f"{len(trims)} variant{'' if len(trims) == 1 else 's'}"] if trims else [])
        cars.append({
            "id": _slug(family),
            "family": family,
            # A family of one model goes by that model (Tiguan R-Line, Golf
            # GTI); Taigun and the Taigun facelift share the family's name.
            "name": models[0]["name"] if len(models) == 1 else _title(family),
            "summary": " · ".join(bits),
            "gearboxes": gearboxes,
            "imported": fam["imported"],
            "models": models,
        })
    cars.sort(key=lambda c: (-busy.get(c["family"], 0), c["name"]))
    _cars_cache = (time.monotonic(), cars)
    return cars


def _car_for(family: str | None, text: str | None, cars: list[dict]) -> str | None:
    """The car a row belongs on: its model's family, or failing that the
    family its free-text model names ('Tiguan' is the Tiguan R-Line)."""
    if family:
        return _slug(family)
    t = (text or "").lower()
    for c in cars:
        if re.search(rf"\b{re.escape(c['family'].lower())}\b", t):
            return c["id"]
    return None


# ------------------------------------------------------------ the endpoints

class BookingIn(BaseModel):
    car_id: str
    date: date
    start: str = Field(pattern=r"^\d{2}:\d{2}$")
    customer: str = Field(min_length=1, max_length=80)
    phone: str = Field(default="", max_length=20)
    consultant: str = Field(default="", max_length=60)
    location: Literal["Showroom", "Home"] = "Showroom"
    address: str = Field(default="", max_length=120)
    source: Literal["AI agent", "Staff", "Walk-in"] = "Staff"
    call_id: Optional[str] = Field(default=None, max_length=64)
    # The enquiry (a drive filed as a request) that this booking settles.
    request_id: Optional[str] = Field(default=None, max_length=32)

    # PII POLICY (2026-10-08): a customer's phone number and home address are
    # never stored (etl/pii.py). The form still takes them - staff may type
    # them - but they are replaced here, before anything is written, and
    # db/pii.sql redacts the same two columns again in the database. A phone
    # or email typed into the name is cut out of it.
    @field_validator("phone", "address")
    @classmethod
    def _no_pii(cls, v):
        return pii.redact(v) or ""

    @field_validator("customer")
    @classmethod
    def _name(cls, v):
        return pii.scrub_text(v)


class BookingPatch(BaseModel):
    status: Literal["booked", "attended", "no_show", "cancelled"]


@router.get("/setup")
def setup():
    """The cars, the team and the day's shape - everything the section draws
    before it has a single drive."""
    cars = _cars()
    with session() as cx:
        team = [r["display_name"] for r in cx.execute(
            "SELECT display_name FROM dim_consultant WHERE is_active ORDER BY display_name"
        ).fetchall()]
    now = _now()
    return {
        "cars": cars,
        "consultants": team,
        "slots": _SLOTS,
        "slot_minutes": SLOT_MINUTES,
        "today": now.date().isoformat(),
        "now": now.strftime("%H:%M"),
    }


@router.get("")
def list_drives(start: date = Query(...), days: int = Query(14, ge=1, le=62),
                samples: bool = Query(True)):
    """Test drives on these days - booked, done, missed or cancelled - and
    every test-drive enquiry: on the day it asks for, or, with no day yet,
    on the day it came in."""
    end = start + timedelta(days=days)
    with session() as cx:
        _lapse(cx)
        return {"bookings": _drives(cx, "on_day >= %s AND on_day < %s", (start, end), samples)}


@router.get("/stats")
def stats(samples: bool = Query(True)):
    """The section's headline: today, the week ahead, the enquiries waiting,
    and how the month's drives turned out."""
    now = _now()
    today, hm = now.date(), now.strftime("%H:%M")
    p = {"t": today, "hm": hm, "m": today.replace(day=1)}
    with session() as cx:
        _lapse(cx)
        keep = "" if samples else _real(cx)
        c = cx.execute(f"""
            SELECT count(*) FILTER (WHERE td_date = %(t)s AND status IN ('booked', 'attended', 'no_show')) AS today,
                   count(*) FILTER (WHERE td_date = %(t)s AND status = 'booked' AND start_time > %(hm)s) AS today_left,
                   count(*) FILTER (WHERE td_date > %(t)s AND td_date <= %(t)s + 7 AND status = 'booked') AS week,
                   count(*) FILTER (WHERE status = 'requested') AS waiting,
                   count(*) FILTER (WHERE status = 'attended' AND td_date BETWEEN %(m)s AND %(t)s) AS attended,
                   count(*) FILTER (WHERE status = 'no_show' AND td_date BETWEEN %(m)s AND %(t)s) AS no_shows,
                   -- booked for a slot that has gone by and not yet marked either way: real
                   -- drives only, as a sample is nobody's to mark
                   count(*) FILTER (WHERE status = 'booked'{_real(cx)}
                                      AND (td_date < %(t)s OR (td_date = %(t)s AND start_time < %(hm)s))) AS unmarked
              FROM dsr.test_drive_booking WHERE TRUE{keep}""", p).fetchone()
        nxt = cx.execute(f"""
            SELECT td_date, start_time, car_id, customer FROM dsr.test_drive_booking
             WHERE status = 'booked' AND (td_date > %(t)s OR (td_date = %(t)s AND start_time > %(hm)s)){keep}
             ORDER BY td_date, start_time LIMIT 1""", p).fetchone()
        busiest = cx.execute(f"""
            SELECT td_date, count(*) AS n FROM dsr.test_drive_booking
             WHERE status = 'booked' AND td_date > %(t)s AND td_date <= %(t)s + 7{keep}
             GROUP BY td_date ORDER BY n DESC, td_date LIMIT 1""", p).fetchone()
    return {
        **{k: c[k] for k in ("today", "today_left", "week", "waiting", "attended", "no_shows", "unmarked")},
        "next": ({"date": nxt["td_date"].isoformat(), "start": nxt["start_time"],
                  "car_id": nxt["car_id"], "customer": nxt["customer"]} if nxt else None),
        "busiest": ({"date": busiest["td_date"].isoformat(), "n": busiest["n"]} if busiest else None),
    }


@router.post("", status_code=201)
def create_booking(b: BookingIn):
    """Book a drive into a slot. Scheduling an enquiry turns that enquiry into
    the booking, rather than the customer ending up with two."""
    if b.car_id not in {c["id"] for c in _cars()}:
        raise HTTPException(422, "No car with that id.")
    if b.start not in _SLOTS:
        raise HTTPException(422, f"Slots run every {SLOT_MINUTES} minutes from {SLOT_START} to {SLOT_END}.")
    now = _now()
    if (b.date, b.start) < (now.date(), now.strftime("%H:%M")):
        raise HTTPException(422, "That time has already gone. Choose a slot from now on.")
    fields =(b.car_id, b.date, b.start, b.customer.strip(), b.phone.strip() or None,
              b.consultant or None, b.location,
              (b.address.strip() or None) if b.location == "Home" else None, b.source)
    with session() as cx:
        try:
            with cx.transaction():
                if b.request_id:
                    req = cx.execute("""SELECT booking_id FROM dsr.test_drive_booking
                                         WHERE booking_id = %s AND status = 'requested' FOR UPDATE""",
                                     (b.request_id,)).fetchone()
                    if not req:
                        raise HTTPException(409, "That enquiry has already been scheduled or cancelled. "
                                                 "Refresh to see where it stands.")
                    row = cx.execute("""
                        UPDATE dsr.test_drive_booking
                           SET car_id = %s, td_date = %s, start_time = %s, customer = %s, phone = %s,
                               consultant = %s, location = %s, address = %s, source = %s,
                               status = 'booked', call_id = coalesce(%s, call_id)
                         WHERE booking_id = %s
                        RETURNING booking_id""",
                        (*fields, b.call_id, req["booking_id"])).fetchone()
                else:
                    row = cx.execute("""
                        INSERT INTO dsr.test_drive_booking
                            (car_id, td_date, start_time, customer, phone, consultant, location,
                             address, source, status, call_id)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'booked', %s)
                        RETURNING booking_id""",
                        (*fields, b.call_id)).fetchone()
        except psycopg.errors.UniqueViolation:
            # One car, one customer, one slot.
            clash = cx.execute(f"""SELECT customer FROM dsr.test_drive_booking
                                    WHERE car_id = %s AND td_date = %s AND start_time = %s
                                      AND status IN ('booked', 'attended', 'no_show'){_real(cx)}""",
                               (b.car_id, b.date, b.start)).fetchone()
            who = clash["customer"] if clash else "someone else"
            raise HTTPException(409, f"{b.start} on that car is already booked for {who}.")
        return _drives(cx, "booking_id = %s", (row["booking_id"],))[0]


@router.patch("/{booking_id}")
def update_booking(p: BookingPatch, booking_id: str = PathParam(..., min_length=6, max_length=32)):
    now = _now()
    with session() as cx:
        if p.status in ("attended", "no_show"):
            # Whether a customer came or not is known only once the drive's time has come.
            at = cx.execute("SELECT td_date, start_time FROM dsr.test_drive_booking WHERE booking_id = %s",
                            (booking_id,)).fetchone()
            if at and at["td_date"] and (at["td_date"], at["start_time"] or "") > (now.date(), now.strftime("%H:%M")):
                raise HTTPException(422, "This drive has not happened yet. Mark it attended or a no-show "
                                         "once its time has come.")
        try:
            row = cx.execute("""UPDATE dsr.test_drive_booking SET status = %s
                                 WHERE booking_id = %s RETURNING booking_id""",
                             (p.status, booking_id)).fetchone()
        except psycopg.errors.CheckViolation:
            raise HTTPException(422, "An enquiry needs a car, a day and a time before it can be booked.")
        except psycopg.errors.UniqueViolation:
            raise HTTPException(409, "That slot has since been booked for someone else.")
        if not row:
            raise HTTPException(404, "No such test drive.")
        return _drives(cx, "booking_id = %s", (row["booking_id"],))[0]


@router.get("/search")
def search(q: str = Query(..., min_length=2, max_length=60), samples: bool = Query(True)):
    """Find a customer's test drives, in any month, by name. Newest first.

    PII POLICY (2026-10-08): this also matched four or more digits of the
    phone. Phone numbers are not stored any more, so it would match nothing
    and look like a customer with no drives; it is by name only."""
    text = q.strip()
    # A typed % or _ is a character to find, not a wildcard.
    name_like = "%" + re.sub(r"([\\%_])", r"\\\1", text) + "%"
    where, params = "customer ILIKE %s", (name_like,)
    with session() as cx:
        found = _drives(cx, where, params, samples)
    found.sort(key=lambda d: d["date"] or d["created_at"][:10], reverse=True)
    return {"results": found[:30]}


def _person(phone: str | None, name: str | None) -> tuple[str, str] | None:
    """A phone and a first name together: one person. A phone alone is not
    enough - the agent's test calls put several names on one number."""
    digits = re.sub(r"\D", "", phone or "")[-10:]
    first = (name or "").strip().split(" ")[0].lower()
    return (digits, first) if len(digits) == 10 and first else None


@router.get("/requests")
def enquiries(calls: bool = Query(True, description="Also read the call log (slow)"),
              samples: bool = Query(True)):
    """Test-drive enquiries waiting for a time.

    `waiting`: drives the database filed as requests - an enquiry whose note
    did not say when, or asked for a slot already taken.

    `requests`: calls in the AI agent's live call log whose summary mentions a
    test drive with nothing on record for the caller from that day on. The car
    is the model family the summary names, and any day or time it mentions is
    passed on as a hint."""
    with session() as cx:
        _lapse(cx)
        real = _drives(cx, samples=False)
        waiting = [d for d in _drives(cx, "status = 'requested'", samples=samples)]
    if not calls:                         # the waiting list alone: a quick read, for live refresh
        return {"waiting": waiting}
    on = lambda d: d["on"]
    from_calls = {d["call_id"] for d in real if d["call_id"] and d["status"] != "cancelled"}
    people: dict[tuple[str, str], list[str]] = {}
    for d in real:
        key = _person(d["phone"], d["customer"])
        if key and d["status"] != "cancelled":
            people.setdefault(key, []).append(on(d))
    try:
        from .calls import list_calls
        log = list_calls().get("calls", [])
    except HTTPException as e:            # no Perfox key on this machine
        return {"waiting": waiting, "requests": [], "unavailable": e.detail}
    cars = _cars()
    out = []
    for c in log:
        summary = c.get("summary") or ""
        if (not _TEST_DRIVE.search(summary) or c.get("id") in from_calls
                or any(day >= (c.get("started_at") or "")[:10]
                       for day in people.get(_person(c.get("phone"), c.get("name")), []))):
            continue
        when = _WHEN.search(summary)
        out.append({
            "call_id": c.get("id"),
            "called_at": c.get("started_at"),
            "name": c.get("name"),
            "phone": c.get("phone"),
            "channel": c.get("channel"),
            "car_id": _car_for(None, summary, cars),
            "when_hint": when.group(1) if when else None,
            "summary": summary,
        })
    return {"waiting": waiting, "requests": out}


# ------------------------------------------------------------ for the agents
#
# The same drives, read for the dashboard's AI agent (app/mcp_server.py) in
# the words the section uses. A sample drive is flagged, and the agent is told
# what that means.

_STATUS_WORDS = {
    "booked": "booked", "attended": "attended", "cancelled": "cancelled", "canceled": "cancelled",
    "no_show": "no_show", "noshow": "no_show", "no-show": "no_show", "missed": "no_show",
    "enquiry": "requested", "enquiries": "requested", "requested": "requested", "waiting": "requested",
}
_LABELS = {"booked": "Booked", "attended": "Attended", "no_show": "No-show",
           "cancelled": "Cancelled", "requested": "Enquiry"}
_SAMPLES_NOTE = ("Drives with sample=true are made-up drives that fill the calendar for showing the "
                 "section, not real customers. Say so whenever you mention one.")


def _agent_day(value: str | None, default: date) -> date:
    """'today', 'tomorrow', 'yesterday' or YYYY-MM-DD, in India's calendar."""
    if not value or not str(value).strip():
        return default
    v = str(value).strip().lower()
    shift = {"today": 0, "tomorrow": 1, "yesterday": -1}
    if v in shift:
        return _now().date() + timedelta(days=shift[v])
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise HTTPException(400, f"Not a day: {value!r}. Use today, tomorrow, yesterday or YYYY-MM-DD.")


def _car_named(name: str, cars: dict[str, str]) -> str:
    want = name.strip().lower()
    for cid, cname in cars.items():
        if want in (cid, cname.lower()) or cname.lower().startswith(want) or want.startswith(cid):
            return cid
    raise HTTPException(400, f"No demo car called {name!r}. The cars: {', '.join(cars.values())}.")


def _agent_row(d: dict, cars: dict[str, str]) -> dict:
    missed = d["status"] == "no_show" and not d["start"]
    waiting = d["status"] == "requested"
    return {
        "date": d["date"],                              # None: an enquiry with no day yet
        "time": d["start"],
        "asked_for": d["asked_time"] if not d["start"] else None,
        "car": cars.get(d["car_id"], "Model not recorded"),
        "customer": d["customer"],
        "phone": d["phone"] or None,
        "executive": d["consultant"] or None,
        "place": f"Home: {d['address']}" if d["location"] == "Home" and d["address"] else d["location"],
        "status": "No-show (enquiry whose day passed with no booking)" if missed
                  else _LABELS.get(d["status"], d["status"]),
        "booked_by": d["source"],
        "enquiry_came_in": d["enquired_on"] if waiting or missed else None,
        "sample": d["sample"],
        "note": (d["note"] or "")[:240] or None,
    }


def _headline(samples: bool, cars: dict[str, str]) -> dict:
    head = stats(samples=samples)
    if head.get("next"):
        head["next"]["car"] = cars.get(head["next"].pop("car_id"), "Model not recorded")
    return head


_COUNTING = ("bookings = drives given a slot: booked, attended or no-show. Cancelled drives, enquiries "
             "waiting for a time, and missed enquiries (the asked-for day passed with no booking) are "
             "counted apart from them. 'real' are customers' drives; 'samples' are made up for "
             "demonstrations.")


def _tally(rows: list[dict]) -> dict:
    """A set of drives counted the way the section reads them."""
    slot = [d for d in rows if d["status"] in ("booked", "attended", "no_show") and d["start"]]
    return {
        "total": len(rows),
        "bookings": len(slot),
        "booked_upcoming": sum(1 for d in slot if d["status"] == "booked"),
        "attended": sum(1 for d in slot if d["status"] == "attended"),
        "no_show": sum(1 for d in slot if d["status"] == "no_show"),
        "cancelled": sum(1 for d in rows if d["status"] == "cancelled"),
        "enquiries_waiting": sum(1 for d in rows if d["status"] == "requested"),
        "missed_enquiries": sum(1 for d in rows if d["status"] == "no_show" and not d["start"]),
    }


def agent_test_drives(date_: str | None = None, date_from: str | None = None, date_to: str | None = None,
                      status: str | None = None, car: str | None = None, search: str | None = None,
                      include_samples: bool = True, limit: int = 60, month: str | None = None,
                      executive: str | None = None) -> dict:
    """Test drives on a day, a span of days or a month (default today), as the
    calendar shows them: drives in their slots, and enquiries on the day they
    ask for or, with no day yet, the day they came in. Filters: status, car,
    and a customer's name or phone. Counted for real drives and for samples
    apart, with the section's headline figures."""
    today = _now().date()
    from .crm_api import span
    named = span(date_) or span(month) if not (date_from or date_to) else None   # "this week", "next month"
    if named:
        lo, hi = named
    elif month and not (date_ or date_from or date_to):
        from .agent_insights import resolve_month
        m = resolve_month(month)
        lo, hi = date.fromisoformat(m["from"]), date.fromisoformat(m["to"])
    else:
        lo = (span(date_from) or (None,))[0] or _agent_day(date_from or date_, today)
        hi = (span(date_to) or (None, None))[1] or _agent_day(date_to or date_, lo)
    if hi < lo:
        lo, hi = hi, lo
    if (hi - lo).days > 370:
        raise HTTPException(400, "Ask for a year or less at a time.")
    where, params = ["on_day BETWEEN %s AND %s"], [lo, hi]
    st = (status or "").strip().lower().replace(" ", "_")
    if st in ("bookings", "booking", "slot", "slots", "booked_drives"):
        # Bookings: drives given a slot - booked, attended or no-show.
        where.append("status IN ('booked', 'attended', 'no_show') AND start_time IS NOT NULL")
    elif st and st not in ("all", "any"):
        s = _STATUS_WORDS.get(st)
        if not s:
            raise HTTPException(400, "status is one of bookings, booked, attended, no_show, cancelled or enquiry.")
        where.append("status = %s")
        params.append(s)
    cars = {c["id"]: c["name"] for c in _cars()}
    if car and car.strip():
        where.append("car_id = %s")
        params.append(_car_named(car, cars))
    if executive and executive.strip():
        where.append("consultant ILIKE %s")
        params.append("%" + re.sub(r"([\\%_])", r"\\\1", executive.strip()) + "%")
    if search and search.strip():
        text = search.strip()
        digits = re.sub(r"\D", "", text)
        like = "%" + re.sub(r"([\\%_])", r"\\\1", text) + "%"
        if len(digits) >= 4:
            where.append("customer ILIKE %s OR regexp_replace(coalesce(phone, ''), '\\D', '', 'g') LIKE %s")
            params += [like, f"%{digits}%"]
        else:
            where.append("customer ILIKE %s")
            params.append(like)
    with session() as cx:
        _lapse(cx)
        rows = _drives(cx, " AND ".join(f"({w})" for w in where), tuple(params), include_samples)
    rows.sort(key=lambda d: (d["on"], d["start"] or d["asked_time"] or "99:99"))
    # Real drives listed first, so a limit never hides a customer behind samples.
    rows.sort(key=lambda d: d["sample"])
    shown = rows[:max(1, min(int(limit), 200))]
    out = {
        "from": lo.isoformat(), "to": hi.isoformat(),
        "today": today.isoformat(), "time_now": _now().strftime("%H:%M"),
        "counting": _COUNTING,
        "real": _tally([d for d in rows if not d["sample"]]),
        "drives": [_agent_row(d, cars) for d in shown],
        "headline": _headline(include_samples, cars),
    }
    if include_samples:
        out["samples"] = _tally([d for d in rows if d["sample"]])
        out["samples_note"] = _SAMPLES_NOTE
    if len(rows) > len(shown):
        out["more"] = f"{len(rows) - len(shown)} more not listed: narrow the days or the filters."
    month_end = (lo.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    period = (f"{lo.day} {lo:%b %Y}" if lo == hi
              else f"{lo:%B %Y}" if lo.day == 1 and hi == month_end
              else f"{lo.day} {lo:%b} - {hi.day} {hi:%b %Y}")
    r, ies = out["real"], (lambda k: "y" if k == 1 else "ies")
    out["answer"] = (
        f"{period}, real test drives: {r['bookings']} booking{'' if r['bookings'] == 1 else 's'} "
        f"({r['booked_upcoming']} upcoming, {r['attended']} attended, {r['no_show']} no-show), "
        f"{r['cancelled']} cancelled, {r['enquiries_waiting']} enquir{ies(r['enquiries_waiting'])} waiting, "
        f"{r['missed_enquiries']} missed enquir{ies(r['missed_enquiries'])}."
        + (f" The calendar also shows {out['samples']['total']} sample drives, made up for demonstrations."
           if include_samples and out["samples"]["total"] else ""))
    # A whole month: the test drives its DSR scorecard records - the
    # dealership's, or the executive's. Asked how many test drives the
    # dealership did in September, the agent answered 0 real from here; the
    # calendar began on 6 Oct 2026, and the September scorecard says 76.
    if lo.day == 1 and hi == month_end:
        from .agent_insights import CALENDAR_START, scorecard_test_drives
        rec = scorecard_test_drives(lo, executive)
        if rec:
            out["scorecard"] = rec
            if hi < CALENDAR_START and not (r["bookings"] or r["cancelled"]):
                also = [f"{r['enquiries_waiting']} test-drive enquir{ies(r['enquiries_waiting'])} from then "
                        f"still waiting for a time" if r["enquiries_waiting"] else "",
                        f"{r['missed_enquiries']} missed" if r["missed_enquiries"] else ""]
                also = " and ".join(a for a in also if a)
                out["answer"] = (
                    f"{rec['answer']} The Test Drives calendar began on 6 Oct 2026, so it has no real drives "
                    f"for {period}" + (f"; {also}" if also else "") + "."
                    + (f" It also shows {out['samples']['total']} sample drives, made up for demonstrations."
                       if include_samples and out["samples"]["total"] else ""))
            else:
                out["answer"] += " " + rec["answer"]
    return out


def agent_test_drive_enquiries(car: str | None = None, include_samples: bool = True,
                               limit: int = 60) -> dict:
    """Test-drive enquiries waiting for a time: a customer asked for a test
    drive and no slot is booked yet. Soonest asked-for day first, then those
    with no day yet."""
    cars = {c["id"]: c["name"] for c in _cars()}
    where, params = ["status = 'requested'"], []
    if car and car.strip():
        where.append("car_id = %s")
        params.append(_car_named(car, cars))
    with session() as cx:
        _lapse(cx)
        rows = _drives(cx, " AND ".join(f"({w})" for w in where), tuple(params), include_samples)
    rows.sort(key=lambda d: (d["date"] or "9999-12-31", d["enquired_on"]))
    rows.sort(key=lambda d: d["sample"])          # real enquiries first
    shown = rows[:max(1, min(int(limit), 200))]
    out = {
        "today": _now().date().isoformat(),
        "total": len(rows),
        "with_a_day": sum(1 for d in rows if d["date"]),
        "day_to_confirm": sum(1 for d in rows if not d["date"]),
        "real": sum(not d["sample"] for d in rows), "samples": sum(d["sample"] for d in rows),
        "enquiries": [_agent_row(d, cars) for d in shown],
    }
    if len(rows) > len(shown):
        out["more"] = f"{len(rows) - len(shown)} more not listed."
    if out["samples"]:
        out["samples_note"] = _SAMPLES_NOTE
    # Test drives promised on a call with nothing saved for the caller: the
    # Enquiries tab's second list, read from the agent's call log.
    try:
        promised = enquiries(calls=True, samples=False).get("requests", [])
    except Exception:                      # the call log is out of reach: say nothing of it
        promised = []
    if car and car.strip():
        promised = [r for r in promised if r.get("car_id") == _car_named(car, cars)]
    out["promised_on_calls"] = [{
        "customer": r.get("name") or "Unknown caller",
        "phone": r.get("phone") or None,
        "car": cars.get(r.get("car_id"), "Not named"),
        "call_day": (r.get("called_at") or "")[:10] or None,
        "asked_for": r.get("when_hint"),
        "summary": (r.get("summary") or "")[:240] or None,
    } for r in promised]
    if promised:
        out["promised_note"] = ("promised_on_calls are calls where the agent discussed or promised a test drive "
                                "and nothing was saved for the caller. They are not in the database yet; the "
                                "team schedules them from the Test Drives page.")
    return out
