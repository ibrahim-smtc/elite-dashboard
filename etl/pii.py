"""
Customer PII protection - the one place that decides what is stored.

PII POLICY (2026-10-08, revised 2026-10-12 and 2026-10-13): a customer's full
phone number and email address are never stored READABLE, and the postal
address is not stored at all.

  * Phone numbers and emails are ENCRYPTED (2026-10-13): the full value is
    stored only as ciphertext, in a companion column (mobile -> mobile_enc,
    email -> email_enc, ...). It is encrypted INSIDE THE DATABASE by the
    db/pii.sql trigger, with a PUBLIC key (OpenPGP, pgcrypto). Nothing on the
    server - not Render, not Supabase - holds the key that decrypts it: the
    private key stays offline with the admin (tools/pii_keys.py). The
    dashboard never decrypts anything.
  * The visible column holds the MASKED value, as below, for everyone.

  * Phone numbers are MASKED: the first three digits are kept and every other
    digit becomes "*" - 9845012345 is stored as 984*******. A +91 or a leading
    0 is dropped first, so the three digits shown are always the start of the
    mobile number itself.
  * Email addresses are MASKED: the first three characters of the name part
    are kept, then "***", then the domain - ravi.kumar@gmail.com is stored as
    rav***@gmail.com. A name part of three characters or fewer shows only its
    first character, so a short address is never shown whole.
  * Postal addresses are REMOVED: the column holds the marker "[REDACTED]",
    so a reader can tell "the customer gave an address and it was removed"
    apart from "no address was given" (NULL).

(Revision 2026-10-12: phone and email were first removed completely, as
"[REDACTED]", like the address. The manager asked for masking instead, so the
team can tell customers apart at a glance. Rows stored before the change keep
"[REDACTED]" - the original values are gone and cannot be masked - until their
month's workbook is uploaded again.)

Free text is different: a booking note or a chat message can carry a phone
number or an email inside a sentence ("call me on 98765 43210"). Those are
masked in place and the rest of the sentence is kept, because the rest is the
substance of the enquiry.

Every function here is idempotent - masking a masked value changes nothing -
because the database trigger runs again on every UPDATE of a row.

Why the encryption happens in the database and not here: the Perfox agent
writes leads straight into Supabase with its own SQL, never through this app.
Only the database trigger sees every writer. So for a phone or email COLUMN the
app now hands the database the cleaned original (clean_phone / clean_email)
and the trigger encrypts it and stores the mask. That is fail-closed twice
over: assert_protected() refuses to send a full value to a database without
db/pii.sql, and a CHECK constraint there rejects any row whose visible column
is not masked - so a disabled trigger blocks the write instead of storing the
number. Free text and names are still masked here as well (scrub_text).

Where this is applied, so a new way in has a list to join:

  * etl/load_dsr.py      Excel workbooks, and sectioned text DSRs
  * etl/text_parser.py   single-table CSV / TXT uploads
  * app/write.py         the dashboard's entry forms (in the payload validators)
  * app/crm_api.py       POST /api/crm/leads (the Perfox agent)
  * app/webhooks.py      POST /api/webhooks/enquiry (the chat widget)
  * app/test_drives.py   the Test Drives board
  * app/calls.py         the Calls page (Perfox call records and transcripts)
  * db/pii.sql           database triggers - the backstop for anything that
                         writes to Supabase without going through this app
                         (the Perfox agent has direct SQL access). Every rule
                         below is written there too, character for character;
                         keep the two in step.

Customer NAMES are not masked: the instruction named phone, email and address,
and the order book cannot work without a name to look an order up by.
"""

from __future__ import annotations

import re

from . import normalize as nz

REDACTED = "[REDACTED]"
# The markers free text carried before 2026-10-12. Text stored then still has
# them; nothing writes them any more.
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

# What a column holds once masked - recognised so masking again is a no-op.
# Unanchored here; db/pii.sql and tools/migrate.py wrap them in ^...$.
MASKED_PHONE_PATTERN = r"[0-9]{3}\*+"
MASKED_EMAIL_PATTERN = r"[^@\s]{0,3}\*\*\*@\S+"

_EMAIL = re.compile(EMAIL_PATTERN)
_MOBILE = re.compile(MOBILE_PATTERN)
_LANDLINE = re.compile(LANDLINE_PATTERN)
_MASKED_PHONE = re.compile(MASKED_PHONE_PATTERN)
_MASKED_EMAIL = re.compile(MASKED_EMAIL_PATTERN)


def mask_digits(text) -> str:
    """
    A phone number, however written, as its first three digits and a "*" for
    each digit after them: "+91 98450 12345" -> "984*******".

    Only the digits count. More than ten (a +91, a leading 0, two numbers run
    together) keeps the last ten, so the three shown are the mobile's own
    first three. Fewer than four digits is not a phone number at all, and is
    removed rather than shown.
    """
    digits = re.sub(r"[^0-9]", "", str(text))[-10:]
    if len(digits) < 4:
        return REDACTED
    return digits[:3] + "*" * (len(digits) - 3)


def mask_email_address(address: str) -> str:
    """One email address as "rav***@gmail.com" - see the module docstring."""
    local, _, domain = address.partition("@")
    visible = local[:3] if len(local) > 3 else local[:1]
    return f"{visible}***@{domain}"


def _trimmed(value) -> str:
    # Excel hands a number typed into a cell over as a float: 9845012345.0.
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def mask_phone(value) -> str | None:
    """
    For a column that holds a phone number. Nothing given stays None; a number
    is masked (mask_digits); a value already masked, or the "[REDACTED]" of a
    row stored before masking, is kept as it is.
    """
    if nz.clean(value) is None:
        return None
    text = _trimmed(value)
    if text == REDACTED or _MASKED_PHONE.fullmatch(text):
        return text
    return mask_digits(re.sub(r"\.0+$", "", text))


def mask_email(value) -> str | None:
    """
    For a column that holds an email address. Nothing given stays None; the
    address is masked (mask_email_address). A value with no recognisable email
    in it is removed ("[REDACTED]"), never shown - it could be anything.
    """
    if nz.clean(value) is None:
        return None
    text = _trimmed(value)
    if text == REDACTED or _MASKED_EMAIL.fullmatch(text):
        return text
    found = _EMAIL.search(text)
    return mask_email_address(found.group(0)) if found else REDACTED


def clean_phone(value) -> str | None:
    """
    A phone COLUMN's value as it is handed to the database, which encrypts it
    and stores the mask (db/pii.sql). Nothing given stays None. Only call this
    for a write to a database that assert_protected() has accepted.
    """
    if nz.clean(value) is None:
        return None
    # Same as dsr.pii_plain(): only an all-digit value loses a trailing ".0".
    return re.sub(r"^([0-9]+)\.0+$", r"\1", _trimmed(value))


def clean_email(value) -> str | None:
    """An email COLUMN's value as it is handed to the database - see clean_phone."""
    if nz.clean(value) is None:
        return None
    return _trimmed(value)


# The databases already checked, by connection string. A database is checked
# once per process: the protection is installed by a migration, not toggled.
_PROTECTED: set[str] = set()


def assert_protected(cx) -> None:
    """
    Refuse to send a full phone number or email to a database that would store
    it readable. db/pii.sql installs the encryption trigger and the CHECK
    constraints that make the database itself refuse an unmasked value; until
    it has been applied, writing clean_phone()/clean_email() values there is
    exactly the leak this module exists to prevent.
    """
    key = cx.info.dsn
    if key in _PROTECTED:
        return
    row = cx.execute(
        "SELECT to_regprocedure('dsr.pii_encrypt(text)') IS NOT NULL "
        "AND EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'lead_mobile_protected') AS ok"
    ).fetchone()
    # The app's pooled connections return rows as dicts; the loader's direct
    # connections return tuples. This must read both: it ran only on tuples in
    # testing, and `row[0]` on a pooled connection raised KeyError, which made
    # every form / agent / webhook write fail with a 500.
    ok = row["ok"] if isinstance(row, dict) else row[0]
    if not ok:
        raise RuntimeError(
            "This database does not have the customer-PII protection installed "
            "(db/pii.sql). Nothing was written. Apply it with: "
            "python tools/migrate.py db/pii.sql --commit")
    _PROTECTED.add(key)


def redact(value) -> str | None:
    """
    For a column that holds a postal address - removed outright.

    Anything given becomes "[REDACTED]"; nothing given stays None. The sheet's
    own blank vocabulary ("-", "N/A", "nil") counts as nothing given, the same
    way normalize.clean() reads it everywhere else.
    """
    return REDACTED if nz.clean(value) is not None else None


def scrub_text(value) -> str | None:
    """
    For free text that may CONTAIN a phone number or an email address.

    Masks them where they stand and keeps the rest of the sentence. Postal
    addresses cannot be found reliably inside free text, so they are only
    removed where they have a column of their own (registration.address).
    """
    if value is None:
        return None
    text = str(value)
    # Emails first, so an address with a number in it (ravi9876543210@gmail.com)
    # is masked whole rather than having its digits masked out of the middle.
    text = _EMAIL.sub(lambda m: mask_email_address(m.group(0)), text)
    text = _MOBILE.sub(lambda m: mask_digits(m.group(0)), text)
    text = _LANDLINE.sub(lambda m: mask_digits(m.group(0)), text)
    return text


def contains_pii(value) -> bool:
    """True if free text still carries a full phone number or email address."""
    if value is None:
        return False
    text = str(value)
    return bool(_EMAIL.search(text) or _MOBILE.search(text) or _LANDLINE.search(text))
