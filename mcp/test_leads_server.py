"""
Tests for mcp/leads_server.py.     python -m pytest mcp/test_leads_server.py

The logic tests need nothing. The database tests run the real INSERT - triggers,
PII encryption and the test-drive parser included - against the database in
DATABASE_URL, which is the LIVE one. They are therefore opt-in
(LEADS_MCP_DB_TESTS=1) and run on a connection that is ALWAYS rolled back, never
committed: nothing is left behind (the lead_id sequence still advances).
"""

from __future__ import annotations

import asyncio
import os
from contextlib import contextmanager
from datetime import datetime, timedelta

import psycopg
import pytest
from fastmcp import Client
from fastmcp.exceptions import ToolError

import leads_server as ls

IST = ls.IST


def at(hh, mm=0, day=26):                      # Mon 26 Oct 2026
    return datetime(2026, 10, day, hh, mm, tzinfo=IST)


# ---------------------------------------------------------------------------
# Pure logic
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("given, want", [
    ("9902344892", "9902344892"),
    ("99023 44892", "9902344892"),
    ("+91 99023-44892", "9902344892"),
    ("+919902344892", "9902344892"),
    ("09902344892", "9902344892"),
])
def test_mobile_ok(given, want):
    assert ls.normalise_mobile(given) == want


@pytest.mark.parametrize("bad", [None, "", "12345", "990234489", "99023448921",
                                 "1234567890", "5902344892", "abc"])
def test_mobile_rejected(bad):
    with pytest.raises(ToolError):
        ls.normalise_mobile(bad)


def test_rating_and_alert_are_gone():
    # Held back pending the manager's approval (see the module docstring).
    for name in ("rating_for", "callback_due"):
        assert not hasattr(ls, name)


def test_hours():
    assert not ls.sales_open(at(10, 14)) and ls.sales_open(at(10, 15))
    assert ls.sales_open(at(18, 29)) and not ls.sales_open(at(18, 30))
    assert ls.service_open(at(9)) and not ls.service_open(at(18))
    assert not ls.service_open(datetime(2026, 11, 1, 12, tzinfo=IST))   # a Sunday


def test_note():
    assert ls.compose_note([], "Taigun, 20 lakh, loan", None, None) == "Taigun, 20 lakh, loan"
    note = ls.compose_note(["FLEET", "FINANCE"], "5 cars", "after 6 PM",
                           "Home test drive: Saturday 11 AM")
    assert note == "[FLEET][FINANCE] Best time to call: after 6 PM. 5 cars | Home test drive: Saturday 11 AM"
    # best time sits before the first "test drive": the database reads a drive slot from there on
    assert note.index("after 6 PM") < note.lower().index("test drive")


# ---------------------------------------------------------------------------
# The tool, with the database stubbed
# ---------------------------------------------------------------------------

@pytest.fixture
def stub(monkeypatch):
    calls = []
    monkeypatch.setattr(ls, "_insert", lambda params: calls.append(params) or 4242)
    monkeypatch.setattr(ls, "_now", lambda: at(12))
    return calls


def call(tool, **args):
    async def run():
        async with Client(ls.mcp) as c:
            return (await c.call_tool(tool, args)).structured_content
    return asyncio.run(run())


def test_tools_listed():
    async def run():
        async with Client(ls.mcp) as c:
            return {t.name for t in await c.list_tools()}
    assert asyncio.run(run()) == {"create_lead", "get_hours_status"}


def test_create_lead_test_drive(stub):
    out = call("create_lead", name="  Ravi   Kumar ", mobile="+91 98450 12345",
               summary="Taigun GT, 20 lakh, loan", lead_type="test_drive", model="Taigun",
               drive_when="Saturday 11 AM", drive_place="home", best_time="after 6 PM",
               trade_in_vehicle="Swift 2018, 40000 km, 1 owner, Bengaluru", tags=["FINANCE"])
    (name, mobile, email, lead_type, model, variant, colour, note, trade_in, tiv), = stub
    assert (name, mobile, email, lead_type, model) == \
        ("Ravi Kumar", "9845012345", None, "test_drive", "Taigun")
    assert trade_in is True and tiv.startswith("Swift")
    assert note == ("[FINANCE][EXCHANGE] Best time to call: after 6 PM. Taigun GT, 20 lakh, loan "
                    "| Home test drive: Saturday 11 AM")
    assert out == {"lead_id": 4242, "lead_id_spoken": "4 2 4 2"}     # no rating, no alert


def test_create_lead_after_hours_and_defaults(stub, monkeypatch):
    monkeypatch.setattr(ls, "_now", lambda: at(21))
    call("create_lead", name="Asha", mobile="9845012345", summary="Wants brochure")
    assert stub[0][3:7] == ("general_enquiry", None, None, None)   # type, model, variant, colour
    assert stub[0][7].startswith("[AFTER-HOURS] Wants brochure")


def test_create_lead_service_uses_service_hours(stub, monkeypatch):
    monkeypatch.setattr(ls, "_now", lambda: at(9, 30))      # service open, sales not yet
    call("create_lead", name="Asha", mobile="9845012345", summary="Service booking", lead_type="service")
    assert stub[0][7].startswith("[SERVICE] ")              # no AFTER-HOURS


def test_create_lead_rejects_bad_input(stub):
    for args in ({"mobile": "12345"}, {"mobile": None}, {"name": "   "},
                 {"email": "not-an-email"}):
        full = {"name": "Asha", "mobile": "9845012345", "summary": "x", **args}
        with pytest.raises(ToolError):
            call("create_lead", **full)
    assert stub == []                                       # nothing reached the database


def test_create_lead_insert_failure_is_clean(monkeypatch):
    monkeypatch.setattr(ls, "_now", lambda: at(12))
    def boom(params):
        raise RuntimeError("connection string postgresql://user:SECRET@host")
    monkeypatch.setattr(ls, "_insert", boom)
    with pytest.raises(ToolError) as e:
        call("create_lead", name="Asha", mobile="9845012345", summary="x")
    assert "could not be saved" in str(e.value) and "SECRET" not in str(e.value)


def test_hours_status(monkeypatch):
    monkeypatch.setattr(ls, "_now", lambda: at(9, 30))
    assert call("get_hours_status") == {"now_ist": "Mon 26 Oct 2026 09:30", "sales_open": False,
                                        "reception_open": False, "service_open": True}


# ---------------------------------------------------------------------------
# The real database (opt-in; always rolled back)
# ---------------------------------------------------------------------------

class RollbackPool:
    """Stands in for ls._db(): a connection that is rolled back on the way out."""

    def __init__(self, probe):
        self.probe, self.found = probe, None

    @contextmanager
    def connection(self):
        cx = psycopg.connect(ls.DSN, prepare_threshold=None,
                             options="-c search_path=dsr,public")      # autocommit off
        try:
            yield cx
            self.found = self.probe(cx)         # look at the row before it is undone
        finally:
            cx.rollback()
            cx.close()


db = pytest.mark.skipif(os.environ.get("LEADS_MCP_DB_TESTS") != "1",
                        reason="set LEADS_MCP_DB_TESTS=1 (uses the live DB, rolled back)")


def run_against_db(monkeypatch, name, **args):
    def probe(cx):
        lead = cx.execute("""SELECT lead_id, mobile, mobile_enc IS NOT NULL, email, email_enc IS NOT NULL,
                                    rating, lead_type, lead_status, origin::text, period_id IS NOT NULL,
                                    source_id IS NOT NULL, model_id IS NOT NULL, dealership, entered_by,
                                    enquiry_note, trade_in, test_drive_given, created_at
                               FROM dsr.lead WHERE lead_name = %s""", (name,)).fetchall()
        drive = cx.execute("""SELECT td_date, asked_time, location, car_id FROM dsr.test_drive_booking
                               WHERE lead_id = (SELECT lead_id FROM dsr.lead WHERE lead_name = %s)""",
                           (name,)).fetchall()
        return lead, drive
    pool = RollbackPool(probe)
    monkeypatch.setattr(ls, "_db", lambda: pool)
    monkeypatch.setattr(ls, "_pii_checked", False)
    out = call("create_lead", name=name, **args)
    return out, pool.found


@db
def test_db_lead_row(monkeypatch):
    name = "ZZ MCP Test Lead"
    out, (lead, drive) = run_against_db(
        monkeypatch, name, mobile="9845012345", email="zz.mcp.test@example.com",
        summary="Taigun GT, 20 lakh, loan, call 9845012345", model="Taigun",
        trade_in_vehicle="Swift 2018, 40000 km, 1 owner, Bengaluru", tags=["FINANCE"])
    (row,) = lead
    (lead_id, mobile, mobile_enc, email, email_enc, rating, lead_type, status, origin, period,
     source, model_id, dealership, entered_by, note, trade_in, drive_given, created_at) = row
    assert lead_id == out["lead_id"]
    assert mobile == "984*******" and mobile_enc            # masked, full number encrypted
    assert email == "zz.***@example.com" and email_enc
    assert "9845012345" not in note                         # the number typed into the note is masked too
    assert (rating, lead_type, status) == (None, "general_enquiry", "new")     # rating is not written, for now
    assert origin == "MANUAL" and period and source and model_id      # filled by lead_fill_direct
    assert (dealership, entered_by, trade_in, drive_given) == \
        ("Elite Motors", "AI Voice/Chat Agent", True, False)
    assert note.startswith("[FINANCE][EXCHANGE] Taigun GT")
    assert abs(created_at - datetime.now(IST).replace(tzinfo=None)) < timedelta(minutes=2)   # IST
    assert drive == []                                      # not a test drive: no booking filed


@db
def test_db_test_drive_is_parsed_not_confused_by_best_time(monkeypatch):
    tomorrow = (datetime.now(IST) + timedelta(days=1)).date()
    _, (lead, drive) = run_against_db(
        monkeypatch, "ZZ MCP Test Drive", mobile="9845012345", lead_type="test_drive",
        summary="Taigun, budget 20 lakh", model="Taigun", drive_when="tomorrow 11 AM",
        drive_place="home", best_time="5 PM")
    assert lead[0][5] is None
    (td_date, asked, location, car), = drive
    assert (td_date, asked, location, car) == (tomorrow, "11:00", "Home", "taigun")   # 11 AM, not the 5 PM call time


@db
def test_db_test_drive_without_slot_stays_a_request(monkeypatch):
    _, (lead, drive) = run_against_db(
        monkeypatch, "ZZ MCP Test Drive No Slot", mobile="9845012345", lead_type="test_drive",
        summary="Tiguan R-Line", model="Tiguan", best_time="4:30 PM")
    (td_date, asked, location, car), = drive
    assert asked is None and td_date is None and location == "Showroom"   # 4:30 PM is a call time, not a drive
