"""
Reveal one customer's full phone number and email - managers only.

ROLE-BASED ACCESS (2026-10-13). Phone numbers and emails are stored encrypted
(db/pii.sql) with a public key; the database cannot read them. A signed-in
manager (app/auth.py) can ask for ONE record at a time: the server passes the
private key - held only in its own secret setting, PII_PRIVATE_KEY - to
dsr.pii_decrypt() for that one query, returns the two values, and writes the
reveal to dsr.pii_reveal_log (who, when, which record). Nothing is decrypted
for anyone else, nor in bulk, nor stored decrypted.

PII_PRIVATE_KEY is the contents of PRIVATE-KEY-backup.asc (tools/pii_keys.py),
pasted as-is (several lines) or base64-encoded on one line.
PII_PRIVATE_KEY_FILE may instead name a file holding it (e.g. a Render secret
file).
"""

from __future__ import annotations

import base64
import logging
import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from .auth import require_manager
from .db import session

log = logging.getLogger("dsr.pii_reveal")

router = APIRouter(prefix="/api/pii", tags=["pii"])

# What can be revealed: (relation, key column, [(answer field, stored column)]).
TABLES = {
    "lead":         ("dsr.lead", "lead_id", [("phone", "mobile"), ("email", "email")]),
    "booking":      ("dsr.booking", "booking_id", [("phone", "mobile")]),
    "registration": ("dsr.registration", "registration_id",
                     [("phone", "contact_no"), ("email", "email")]),
}


def private_key() -> str:
    path = os.environ.get("PII_PRIVATE_KEY_FILE", "").strip()
    raw = Path(path).read_text(encoding="ascii") if path else os.environ.get("PII_PRIVATE_KEY", "")
    raw = raw.strip()
    if not raw:
        raise HTTPException(503, "Revealing contacts is not set up on this server "
                                 "(PII_PRIVATE_KEY is missing).")
    if "BEGIN PGP" not in raw:
        try:
            raw = base64.b64decode(raw).decode("ascii")
        except Exception as exc:
            raise HTTPException(503, "PII_PRIVATE_KEY is not a usable key.") from exc
    # Some hosts store a pasted multi-line value with literal "\n".
    return raw.replace("\\n", "\n")


class RevealIn(BaseModel):
    table: Literal["lead", "booking", "registration"]
    id: int


@router.post("/reveal")
def reveal(body: RevealIn, user: dict = Depends(require_manager)):
    rel, pk, fields = TABLES[body.table]
    key = private_key()
    select = ", ".join(
        f"{col} AS {name}_masked, dsr.pii_decrypt({col}_enc, k.key) AS {name}"
        for name, col in fields)
    try:
        with session() as cx:
            with cx.transaction():
                row = cx.execute(
                    f"SELECT {select} FROM {rel}, (SELECT %s::text AS key) k WHERE {pk} = %s",
                    (key, body.id)).fetchone()
                if row is None:
                    raise HTTPException(404, "No such record.")
                cx.execute(
                    "INSERT INTO dsr.pii_reveal_log (user_email, table_name, row_id, fields) "
                    "VALUES (%s, %s, %s, %s)",
                    (user["email"], body.table, str(body.id), [name for name, _ in fields]))
    except HTTPException:
        raise
    except Exception as exc:
        # The message is the database's ("Wrong key or corrupt data"); the key
        # itself was a bound parameter and is never in it.
        log.error("reveal of %s %s failed: %s", body.table, body.id, exc)
        raise HTTPException(500, "The contact could not be decrypted on this server.") from None

    out = {"table": body.table, "id": body.id}
    for name, _ in fields:
        out[name] = row[name]
        out[f"{name}_masked"] = row[f"{name}_masked"]
    out["encrypted"] = any(row[name] is not None for name, _ in fields)
    if not out["encrypted"]:
        out["note"] = ("No full number or email is stored for this record - it was saved "
                       "before encryption began (13 Oct 2026), or none was given.")
    return out
