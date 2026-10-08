"""
The agent's call log, proxied.

Perfox answers the phone; the dashboard reports on the dealership. Until now
those were separate places to look, and nobody on the floor was going to open
two systems to find out what the agent had been telling customers all morning.

Three routes, all thin wrappers over the Perfox API:

    GET /api/calls                     what was taken, when, by whom, and why
    GET /api/calls/{id}/transcript     what was said, turn by turn
    GET /api/calls/{id}/recordings     playback URLs for one call

The transcript is the one worth having. A recording needs someone to sit and
listen to it; the transcript can be read in ten seconds, searched, and pasted
into a follow-up - and these calls switch between English, Hindi and Punjabi
mid-sentence, which no summary line captures.

They are proxies rather than a fetch from the browser for one reason: the
Perfox key. A call made from the page would ship that key inside the bundle,
where anyone who opens devtools has it - and it reads every customer
conversation the dealership has ever had. It stays in the environment on this
side and the browser never sees it.

Recordings are deliberately NOT fetched with the list and never cached. The
URLs Perfox returns are presigned and expire in fifteen minutes, so a URL
handed out with the list would be dead before most people scrolled to it. They
are fetched when a call is actually opened.
"""

import logging
import os
import re
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Path

from etl import pii

log = logging.getLogger("dsr.calls")

router = APIRouter(prefix="/api/calls", tags=["agent-calls"])

BASE = os.environ.get("PERFOX_API_BASE", "https://elite-motors-api.perfox.ai").rstrip("/")

# Long enough for a slow upstream, short enough that a hanging Perfox does not
# hold a dashboard request open until the gateway kills it at sixty seconds.
_TIMEOUT = httpx.Timeout(20.0, connect=8.0)


def _key() -> str:
    key = os.environ.get("PERFOX_API_KEY", "").strip()
    if not key:
        # 503 rather than 500: nothing is broken, the integration is simply not
        # configured, and the panel says so instead of showing a stack trace.
        raise HTTPException(
            status_code=503,
            detail="PERFOX_API_KEY is not set, so the agent's call log cannot be read.",
        )
    return key


def _get(path: str) -> Any:
    """One GET against Perfox, with its errors turned into ours."""
    try:
        with httpx.Client(timeout=_TIMEOUT) as client:
            r = client.get(f"{BASE}{path}",
                           headers={"Authorization": f"Bearer {_key()}"})
    except httpx.TimeoutException:
        raise HTTPException(504, "The agent's call service did not respond in time.")
    except httpx.HTTPError as exc:
        log.warning("perfox request failed: %s", exc)
        raise HTTPException(502, "Could not reach the agent's call service.")

    if r.status_code == 401:
        raise HTTPException(502, "The agent's call service rejected our API key.")
    if r.status_code == 404:
        raise HTTPException(404, "No such call.")
    if r.status_code >= 400:
        # The upstream body can carry the key back in an error echo, so it is
        # logged and not returned.
        log.warning("perfox %s -> %s: %s", path, r.status_code, r.text[:300])
        raise HTTPException(502, f"The agent's call service returned {r.status_code}.")

    try:
        return r.json()
    except ValueError:
        raise HTTPException(502, "The agent's call service returned something unreadable.")


# FIX (2026-10-09): the call transcript and the one-line summary are what was
# SAID on the call, and customers read their phone number out ("Mera mobile
# number hai 8822441722"). The Calls page relays that text to every browser, so
# a number spoken on a call was shown in full next to a redacted caller column.
# etl.pii.scrub_text catches an ordinary number and an email; a speech-to-text
# transcript also writes a number digit by digit ("8 8 2 2 4 4 1 7 2 2") or in
# groups, which that pattern does not. Any run of ten or more digits, with
# single spaces or hyphens between them, is therefore treated as a phone number
# here. A six-digit reference number the agent reads back is left alone. What
# can NOT be caught: digits spoken as words ("eight eight two...", or in Hindi),
# and any address - and the audio recording itself is Perfox's file, not ours.
_SPOKEN_NUMBER = re.compile(r"(?<![0-9])(?:[0-9][ -]?){9,}[0-9](?![0-9])")


def _scrub_spoken(text: str | None) -> str | None:
    """Phone numbers and emails out of what was said on a call."""
    text = pii.scrub_text(text)
    if text is None:
        return None
    return _SPOKEN_NUMBER.sub(pii.PHONE_MARK, text)


def _seconds(v: Any) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


# Perfox scores a handful of things out of ten. Only two are worth a column:
# whether the customer got what they came for, and how they sounded doing it.
# The direction was checked against the summaries rather than assumed - a 0
# reads "the customer requested a manager after the agent failed to address
# it", a 10 reads "successfully scheduled a test drive".
def _sentiment(score: Any) -> str | None:
    if score is None:
        return None
    try:
        n = int(score)
    except (TypeError, ValueError):
        return None
    # Banded rather than matched exactly, so a 3 or a 7 still lands somewhere
    # if Perfox ever scores off the current 0/5/10 steps.
    if n <= 2:
        return "negative"
    if n >= 8:
        return "positive"
    return "neutral"


def _verdict(resolution: Any, status: str | None) -> str:
    """
    What the call needs next, rather than what it was.

    `resolution` is the QA judgement that the customer's need was met, and it is
    the only field that speaks to an outcome. `status` is a lifecycle state and
    disagrees with it on three calls - two say resolved while scoring zero - so
    resolution wins and status only distinguishes a call that was abandoned
    from one that simply ended without getting anywhere.
    """
    try:
        res = int(resolution) if resolution is not None else None
    except (TypeError, ValueError):
        res = None
    if res is not None and res >= 8:
        return "Resolved"
    if (status or "").lower() == "abandoned":
        return "Abandoned"
    if res is None:
        return "Unscored"
    return "Needs follow-up"


def _cases_by_id() -> dict:
    """
    Every case, keyed by conversation id.

    /cases is the only endpoint carrying qa_scores, and it paginates - the
    default page of 20 covered 15 of 32 calls, so asking for 100 brings all 52
    in one request and every call finds its case. A failure here is not fatal:
    the call log is still worth showing without the two scored columns.
    """
    try:
        payload = _get("/api/v1/cases?page=1&page_size=100")
    except HTTPException:
        log.warning("cases unavailable; calls will render without QA columns")
        return {}
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        return {}
    return {r["id"]: r for r in rows if r.get("id")}


@router.get("")
def list_calls():
    """
    Every call the agent has handled, newest first.

    Passed through close to as received - this is Perfox's record, not ours,
    and rewriting it here would mean two places to change when they add a
    field. Only three things are done: the caller is flattened out of the
    nested end_user object so the table can read it, the order is fixed so the
    most recent call is at the top, and totals are counted once here rather
    than in the browser.

    `direction` is dropped. Every one of the 32 calls on record says "unknown",
    so a column of it would be a column of nothing.
    """
    payload = _get("/api/v1/calls")
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        rows = []

    cases = _cases_by_id()

    calls = []
    for c in rows:
        user = c.get("end_user") or {}
        case = cases.get(c.get("conversation_id")) or {}
        qa = case.get("qa_scores") or {}
        calls.append({
            "id": c.get("conversation_id"),
            "customer_id": c.get("customer_id"),
            "name": pii.scrub_text((user.get("name") or "").strip() or None),
            # PII POLICY (2026-10-08): the caller's number is Perfox's record and
            # none of it is stored here, but this route hands it to every browser
            # that opens the Calls page - so it is replaced on the way through.
            # The name is kept; a phone or email in it is cut out.
            "phone": pii.redact(user.get("phone")),
            "channel": c.get("channel"),
            "status": c.get("status"),
            "started_at": c.get("started_at"),
            "ended_at": c.get("ended_at"),
            "duration_seconds": _seconds(c.get("duration_seconds")),
            "has_recording": bool(c.get("has_recording")),
            "summary": _scrub_spoken((c.get("summary") or "").strip() or None),
            # From the case, which is where Perfox keeps its QA scoring. Null
            # when a call has no case rather than guessed at.
            "sentiment": _sentiment(qa.get("sentiment")) if qa else None,
            "sentiment_score": qa.get("sentiment") if qa else None,
            "verdict": _verdict(qa.get("resolution"), case.get("status")) if qa else None,
            "qa_overall": qa.get("overall") if qa else None,
        })

    calls.sort(key=lambda c: c.get("started_at") or "", reverse=True)

    return {
        "calls": calls,
        "total": len(calls),
        "recorded": sum(1 for c in calls if c["has_recording"]),
        "talk_seconds": sum(c["duration_seconds"] for c in calls),
        "channels": sorted({c["channel"] for c in calls if c["channel"]}),
        "scored": sum(1 for c in calls if c["verdict"]),
        "resolved": sum(1 for c in calls if c["verdict"] == "Resolved"),
        "negative": sum(1 for c in calls if c["sentiment"] == "negative"),
    }


@router.get("/{conversation_id}/transcript")
def call_transcript(conversation_id: str = Path(..., min_length=8, max_length=64)):
    """
    What was actually said on one call.

    Perfox keeps a transcript as an event stream rather than a list of turns:
    call_started, user_message, tool_call, tool_result, ai_response, call_ended.
    The turns are what a sales manager reads, so those are lifted out; the tool
    calls are returned separately and counted, because "the agent looked it up"
    is worth knowing without nine rows of plumbing in the middle of the
    conversation.

    Paged defensively. One request with a high limit covers every call on
    record - the longest is 64 events - but `after` is a timestamp rather than
    a cursor, and a tool_call and its tool_result routinely share one to the
    millisecond. Paging on that alone would silently drop whichever fell on the
    boundary, so pages are de-duplicated by event id and the loop is capped.
    """
    seen: set[str] = set()
    events: list[dict] = []
    after: str | None = None
    truncated = False

    for _ in range(10):
        q = "?limit=500" + (f"&after={quote(after)}" if after else "")
        payload = _get(f"/api/v1/conversations/{conversation_id}/events{q}")
        page = payload.get("data") if isinstance(payload, dict) else payload
        if not isinstance(page, list) or not page:
            break

        fresh = [e for e in page if e.get("id") and e["id"] not in seen]
        for e in fresh:
            seen.add(e["id"])
        events.extend(fresh)

        if not (isinstance(payload, dict) and payload.get("has_more")):
            break
        nxt = page[-1].get("created_at")
        # No timestamp to page on, or it has not moved: stop rather than ask
        # for the same window forever.
        if not nxt or nxt == after:
            truncated = True
            break
        after = nxt
    else:
        truncated = True

    events.sort(key=lambda e: e.get("created_at") or "")

    turns, tools = [], []
    for e in events:
        kind = e.get("event_type")
        if kind in ("user_message", "ai_response"):
            text = (e.get("text") or "").strip()
            if text:
                turns.append({
                    "who": "customer" if kind == "user_message" else "agent",
                    "text": _scrub_spoken(text),
                    "at": e.get("created_at"),
                })
        elif kind == "tool_call":
            tools.append({"name": e.get("tool_name"), "at": e.get("created_at")})

    return {
        "id": conversation_id,
        "turns": turns,
        "tools": tools,
        "events": len(events),
        "truncated": truncated,
    }


@router.get("/{conversation_id}/recordings")
def call_recordings(conversation_id: str = Path(..., min_length=8, max_length=64)):
    """
    Playback URLs for one call, fetched at the moment it is opened.

    A call has two legs - what the customer said and what the agent said - and
    they come back as separate audio files, so both are returned rather than
    guessing which one is wanted.

    `expires_in_seconds` is passed through so the page knows the links go stale.
    They are presigned and last fifteen minutes, which is why nothing here is
    cached: a cached URL is a broken player.
    """
    payload = _get(f"/api/v1/conversations/{conversation_id}/recordings")
    recs = payload.get("recordings") if isinstance(payload, dict) else None
    if not isinstance(recs, list):
        recs = []

    return {
        "id": conversation_id,
        "expires_in_seconds": payload.get("expires_in_seconds") if isinstance(payload, dict) else None,
        "recordings": [{"leg": r.get("leg"), "url": r.get("url")}
                       for r in recs if r.get("url")],
    }
