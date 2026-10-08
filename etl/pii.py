"""
Customer PII redaction - the one place that decides what is never stored.

PII POLICY (2026-10-08): a customer's phone number, email address and postal
address must not reach the database. They are removed completely - not masked,
not hashed - and the column holds the marker "[REDACTED]" instead, so a reader
can tell "the customer gave a phone number and it was removed" apart from "no
phone number was given" (NULL).

Free text is different: a booking note or a chat message can carry a phone
number or an email inside a sentence ("call me on 98765 43210"). Those are cut
out of the sentence and the rest of it is kept, because the rest is the
substance of the enquiry.

Where this is applied, so a new way in has a list to join:

  * etl/load_dsr.py      Excel workbooks, and sectioned text DSRs
  * etl/text_parser.py   single-table CSV / TXT uploads
  * app/write.py         the dashboard's entry forms (in the payload validators)
  * app/crm_api.py       POST /api/crm/leads (the Perfox agent)
  * app/webhooks.py      POST /api/webhooks/enquiry (the chat widget)
  * db/pii.sql           database triggers - the backstop for anything that
                         writes to Supabase without going through this app
                         (the Perfox agent has direct SQL access). The patterns
                         below are written there too; keep the two in step.

Customer NAMES are not redacted: the instruction named phone, email and
address, and the order book cannot work without a name to look an order up by.
"""

from __future__ import annotations

import re

from . import normalize as nz

REDACTED = "[REDACTED]"
PHONE_MARK = "[PHONE REDACTED]"
EMAIL_MARK = "[EMAIL REDACTED]"

# Written so the identical text is valid in Python `re` and in Postgres regular
# expressions (db/pii.sql) - no \d, no named groups.
EMAIL_PATTERN = r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}"

# An Indian mobile, however it is written: 9876543210, 98765 43210,
# 98765-43210, 987-654-3210, +91 98765 43210, +919876543210, 09876543210.
# The digit look-arounds stop it biting into a longer number.
MOBILE_PATTERN = (r"(?<![0-9])(\+?91[ -]?|0)?"
                  r"([6-9][0-9]{4}[ -]?[0-9]{5}|[6-9][0-9]{2}[ -][0-9]{3}[ -][0-9]{4})"
                  r"(?![0-9])")

# A landline with its STD code: 080-41234567, 08041234567, 0124 4567890.
LANDLINE_PATTERN = r"(?<![0-9])0[0-9]{2,4}[ -]?[0-9]{6,8}(?![0-9])"

_EMAIL = re.compile(EMAIL_PATTERN)
_MOBILE = re.compile(MOBILE_PATTERN)
_LANDLINE = re.compile(LANDLINE_PATTERN)


def redact(value) -> str | None:
    """
    For a column that holds nothing BUT a phone, an email or an address.

    Anything given becomes "[REDACTED]"; nothing given stays None. The sheet's
    own blank vocabulary ("-", "N/A", "nil") counts as nothing given, the same
    way normalize.clean() reads it everywhere else.
    """
    return REDACTED if nz.clean(value) is not None else None


def scrub_text(value) -> str | None:
    """
    For free text that may CONTAIN a phone number or an email address.

    Cuts those out and keeps the rest of the sentence. Postal addresses cannot
    be found reliably inside free text, so they are only removed where they
    have a column of their own (registration.address).
    """
    if value is None:
        return None
    text = str(value)
    # Emails first, so an address with a number in it (ravi9876543210@gmail.com)
    # is removed whole rather than having its digits cut out of the middle.
    text = _EMAIL.sub(EMAIL_MARK, text)
    text = _MOBILE.sub(PHONE_MARK, text)
    text = _LANDLINE.sub(PHONE_MARK, text)
    return text


def contains_pii(value) -> bool:
    """True if free text still carries a phone number or an email address."""
    if value is None:
        return False
    text = str(value)
    return bool(_EMAIL.search(text) or _MOBILE.search(text) or _LANDLINE.search(text))
