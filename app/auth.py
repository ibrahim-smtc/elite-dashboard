"""
Dashboard sign-in and roles.

ROLE-BASED ACCESS (2026-10-13): the dashboard is behind a sign-in page. There
are two roles:

  manager   the dashboard, plus revealing one customer's full phone number and
            email at a time (app/pii_reveal.py; every reveal is logged)
  employee  the dashboard, with phone numbers and emails masked only

How the pieces fit:

  * Passwords are Supabase Auth's job. Accounts are created in the Supabase
    dashboard (Authentication > Users); this app never stores or sees a
    password beyond passing it to Supabase once at sign-in.
  * dsr.dashboard_user (db/auth.sql) is the list of who may sign in and as
    what. An account that is not on it is refused even with the right
    password, so an account created by mistake in Supabase gets nothing.
  * Sign-in goes through this server (POST /api/auth/login), which keeps the
    Supabase session in two HttpOnly cookies - the browser's JavaScript cannot
    read them, and every request the dashboard already makes carries them, the
    live-update stream included.
  * Each request's token is verified HERE, against the project's published
    signing keys (JWKS), not by asking Supabase every time.

What is NOT behind sign-in, because a machine calls it and cannot use a login
page: the Perfox agent's API (/api/crm/*, /mcp, /agent/*) and the chat
webhook (/api/webhooks/*). None of them ever returns a full phone number or
email. The page itself (/, /static/*) is public too - it holds no data, and it
shows the sign-in form until /api/auth/me says who is there.

Needs, on the server:
  SUPABASE_ANON_KEY   the project's public (anon / publishable) API key -
                      Supabase > Project Settings > API Keys. Not a secret.
  SUPABASE_URL        optional; worked out from DATABASE_URL when unset.
Without SUPABASE_ANON_KEY nobody can sign in (fail closed: the dashboard does
not fall back to being open).
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import threading
import time
from typing import Optional

import httpx
import jwt
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .db import session

log = logging.getLogger("dsr.auth")

router = APIRouter(prefix="/api/auth", tags=["auth"])

SESSION_COOKIE = "eds_session"   # the Supabase access token
REFRESH_COOKIE = "eds_refresh"   # the Supabase refresh token
REFRESH_MAX_AGE = 30 * 24 * 3600

# Called by machines that cannot sign in. Everything else under /api/ needs a
# signed-in, listed account.
PUBLIC_PREFIXES = ("/api/auth/", "/api/crm/", "/api/webhooks/")


def needs_sign_in(path: str) -> bool:
    return path.startswith("/api/") and not path.startswith(PUBLIC_PREFIXES)


# ---------------------------------------------------------------- configuration

def project_url() -> str:
    url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if url:
        return url
    # The Supabase pooler user is "postgres.<project-ref>".
    m = re.search(r"//postgres\.([a-z0-9]+)[:@]", os.environ.get("DATABASE_URL", ""))
    return f"https://{m.group(1)}.supabase.co" if m else ""


def anon_key() -> str:
    return (os.environ.get("SUPABASE_ANON_KEY")
            or os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "").strip()


def _configured() -> None:
    if not (project_url() and anon_key()):
        raise HTTPException(503, "Sign-in is not set up on this server yet "
                                 "(SUPABASE_ANON_KEY is missing).")


# ---------------------------------------------------------------- tokens

_jwks: Optional[jwt.PyJWKClient] = None
_jwks_lock = threading.Lock()


def _signing_key(token: str):
    """The project's public key that signed this token (JWKS, cached an hour)."""
    global _jwks
    with _jwks_lock:
        if _jwks is None:
            _jwks = jwt.PyJWKClient(f"{project_url()}/auth/v1/.well-known/jwks.json",
                                    cache_keys=True, lifespan=3600)
    return _jwks.get_signing_key_from_jwt(token).key


def verify(token: str) -> dict:
    """The token's claims, if Supabase signed it, for this project, and it is
    still valid. Raises jwt.PyJWTError otherwise."""
    return jwt.decode(token, _signing_key(token), algorithms=["ES256", "RS256"],
                      audience="authenticated", issuer=f"{project_url()}/auth/v1",
                      leeway=30)


def _supabase_token(grant: str, body: dict) -> Optional[dict]:
    """POST /auth/v1/token. The tokens, or None when Supabase says no."""
    _configured()
    try:
        r = httpx.post(f"{project_url()}/auth/v1/token", params={"grant_type": grant},
                       json=body, headers={"apikey": anon_key()}, timeout=15)
    except httpx.HTTPError as exc:
        log.warning("Supabase Auth unreachable: %s", exc)
        raise HTTPException(503, "The sign-in service could not be reached. Try again.") from exc
    if r.status_code == 200:
        return r.json()
    log.info("Supabase Auth refused a %s grant: %s", grant, r.status_code)
    return None


# Several requests arrive together with the same expired token (the dashboard
# loads in one burst); one refresh serves them all for a minute.
_refreshed: dict[str, tuple[float, dict]] = {}
_refresh_lock = threading.Lock()


def _refresh(refresh_token: str) -> Optional[dict]:
    h = hashlib.sha256(refresh_token.encode()).hexdigest()
    with _refresh_lock:
        now = time.time()
        for k in [k for k, (t, _) in _refreshed.items() if now - t > 60]:
            _refreshed.pop(k, None)
        hit = _refreshed.get(h)
        if hit:
            return hit[1]
        tokens = _supabase_token("refresh_token", {"refresh_token": refresh_token})
        if tokens:
            _refreshed[h] = (now, tokens)
        return tokens


# ---------------------------------------------------------------- roles

_roles: dict[str, tuple[float, Optional[str]]] = {}


def role_for(email: str) -> Optional[str]:
    """'manager', 'employee', or None (not allowed in). Cached for a minute."""
    email = (email or "").strip().lower()
    if not email:
        return None
    hit = _roles.get(email)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    with session() as cx:
        row = cx.execute("SELECT role FROM dsr.dashboard_user WHERE email = %s",
                         (email,)).fetchone()
    role = (row["role"] if isinstance(row, dict) else row[0]) if row else None
    _roles[email] = (time.time(), role)
    return role


# ---------------------------------------------------------------- the session

def current_user(request: Request) -> tuple[Optional[dict], Optional[dict]]:
    """(user, refreshed tokens). user is {email, role} or None when nobody is
    signed in; role is None when the account is not on the list."""
    access = request.cookies.get(SESSION_COOKIE)
    refresh = request.cookies.get(REFRESH_COOKIE)
    if not (access or refresh) or not (project_url() and anon_key()):
        return None, None
    claims, new = None, None
    if access:
        try:
            claims = verify(access)
        except jwt.PyJWTError:
            claims = None
    if claims is None and refresh:
        new = _refresh(refresh)
        if new:
            try:
                claims = verify(new["access_token"])
            except jwt.PyJWTError:
                claims, new = None, None
    if not claims:
        return None, None
    email = (claims.get("email") or "").lower()
    return {"email": email, "role": role_for(email)}, new


def _secure(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    return proto.split(",")[0].strip() == "https"


def set_session(response, request: Request, tokens: dict) -> None:
    secure = _secure(request)
    response.set_cookie(SESSION_COOKIE, tokens["access_token"],
                        max_age=int(tokens.get("expires_in") or 3600), httponly=True,
                        secure=secure, samesite="lax", path="/")
    response.set_cookie(REFRESH_COOKIE, tokens["refresh_token"], max_age=REFRESH_MAX_AGE,
                        httponly=True, secure=secure, samesite="lax", path="/")


def clear_session(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path="/")


async def gate(request: Request, call_next):
    """HTTP middleware: every dashboard API call needs a signed-in, listed account."""
    if not needs_sign_in(request.url.path):
        return await call_next(request)
    try:
        user, new = await run_in_threadpool(current_user, request)
    except HTTPException as exc:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    except Exception:
        log.exception("sign-in check failed")
        return JSONResponse({"detail": "Could not check who is signed in."}, status_code=503)
    if user is None:
        resp = JSONResponse({"detail": "Sign in to use the dashboard."}, status_code=401)
        if request.cookies.get(SESSION_COOKIE) or request.cookies.get(REFRESH_COOKIE):
            clear_session(resp)
        return resp
    if user["role"] is None:
        return JSONResponse({"detail": "This account is not allowed to use the dashboard. "
                                       "Ask the manager to add it."}, status_code=403)
    request.state.user = user
    response = await call_next(request)
    if new:
        set_session(response, request, new)
    return response


# ---------------------------------------------------------------- routes

class SignIn(BaseModel):
    email: str = Field(..., min_length=3, max_length=254)
    password: str = Field(..., min_length=1, max_length=200)


@router.post("/login")
def login(body: SignIn, request: Request):
    tokens = _supabase_token("password", {"email": body.email.strip(), "password": body.password})
    if not tokens:
        raise HTTPException(401, "Wrong email or password.")
    try:
        claims = verify(tokens["access_token"])
    except jwt.PyJWTError as exc:
        log.warning("Supabase returned a token that does not verify: %s", exc)
        raise HTTPException(503, "Sign-in is misconfigured on this server.") from exc
    email = (claims.get("email") or "").lower()
    role = role_for(email)
    if role is None:
        raise HTTPException(403, "This account is not allowed to use the dashboard. "
                                 "Ask the manager to add it.")
    resp = JSONResponse({"email": email, "role": role})
    set_session(resp, request, tokens)
    return resp


@router.get("/me")
def me(request: Request):
    user, new = current_user(request)
    if user is None:
        raise HTTPException(401, "Not signed in.")
    if user["role"] is None:
        raise HTTPException(403, "This account is not allowed to use the dashboard.")
    resp = JSONResponse(user)
    if new:
        set_session(resp, request, new)
    return resp


@router.post("/logout")
def logout(request: Request):
    access = request.cookies.get(SESSION_COOKIE)
    if access and project_url() and anon_key():
        # Revokes the refresh token at Supabase too; best effort.
        try:
            httpx.post(f"{project_url()}/auth/v1/logout", timeout=10,
                       headers={"apikey": anon_key(), "Authorization": f"Bearer {access}"})
        except httpx.HTTPError:
            pass
    resp = JSONResponse({"signed_out": True})
    clear_session(resp)
    return resp


def require_manager(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "manager":
        raise HTTPException(403, "Only a manager can see full phone numbers and emails.")
    return user
