"""
Cleaning helpers for the DSR workbook.

The workbook is maintained by hand, so the same fact arrives spelled several ways:
"ABINAND P" / "ABHINAND P" / "Abinand P", "Walk In" / "WALKIN", "Taigun (FL)" /
"TAIGUN (FL)". Everything here exists to fold those onto one canonical value so the
database can carry real foreign keys instead of free text.
"""

from __future__ import annotations

import re
from datetime import date, datetime, time

# Values the sheet uses to mean "nothing here". Excel formula errors land in this
# set too - they must never reach a numeric column.
BLANKS = {
    "", "-", "--", "n/a", "na", "nil", "none", "null",
    "#div/0!", "#value!", "#ref!", "#n/a", "#name?", "#num!",
}


def clean(value) -> str | None:
    """Collapse whitespace, drop the blank vocabulary above. Returns None or text."""
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    if text.lower() in BLANKS:
        return None
    return text


def upper(value) -> str | None:
    text = clean(value)
    return text.upper() if text else None


def title(value) -> str | None:
    """Title case for display, preserving short initials (K R, A, P, KB)."""
    text = clean(value)
    if not text:
        return None
    parts = []
    for word in text.split(" "):
        parts.append(word.upper() if len(word) <= 2 else word.capitalize())
    return " ".join(parts)


def as_int(value) -> int | None:
    text = clean(value)
    if text is None:
        return None
    try:
        return int(round(float(text.replace(",", ""))))
    except (ValueError, TypeError):
        return None


def as_num(value) -> float | None:
    text = clean(value)
    if text is None:
        return None
    try:
        return float(text.replace(",", "").replace("%", ""))
    except (ValueError, TypeError):
        return None


_DATE_FORMATS = (
    "%d/%m/%Y %I:%M %p", "%d/%m/%Y %H:%M", "%d/%m/%Y",
    "%d-%m-%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d",
)


def as_datetime(value) -> datetime | None:
    """
    Parse a cell into a datetime.

    Real dates arrive from openpyxl already typed. The CRM exports on the TD and
    TD Leads tabs arrive as text and are day-first ("31/7/2024 8:38 pm") - parsing
    those month-first would silently move records into the wrong month.
    """
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    text = clean(value)
    if text is None:
        return None
    text = text.replace(" pm", " PM").replace(" am", " AM")
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def as_date(value) -> date | None:
    parsed = as_datetime(value)
    return parsed.date() if parsed else None


def as_time(value) -> time | None:
    if isinstance(value, time):
        return value
    if isinstance(value, datetime):
        return value.time()
    text = clean(value)
    if text is None:
        return None
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(text, fmt).time()
        except ValueError:
            continue
    return None


_TRUE = {"yes", "y", "true", "1", "done", "completed"}
_FALSE = {"no", "n", "false", "0", "not done", "pending"}


def as_bool(value) -> bool | None:
    text = clean(value)
    if text is None:
        return None
    low = text.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    return None


def as_bool_lease(value) -> bool | None:
    """
    Like as_bool, but "LEASING" counts as true.

    On the Reg Report the insurance column reads LEASING for lease deals: the car is
    insured, the lessor just arranges the cover instead of the dealership. Treating
    that as "no insurance" would understate the attachment rate.
    """
    text = clean(value)
    if text and text.lower() in {"leasing", "lease"}:
        return True
    return as_bool(value)


# ---------------------------------------------------------------------
# Sales consultants
# ---------------------------------------------------------------------

# The Book Comm VS Ach and Daily Tracker tabs use shorthand and outright
# misspellings. Left side is what the sheet says, right side is canonical.
CONSULTANT_ALIASES = {
    "AKILESH": "AKHILESH",
    "ABHINAND P": "ABINAND P",
    "ABHINAND": "ABINAND P",
    "ABINAND": "ABINAND P",
    "ABBAS": "SIKKANDER ABBAS",
    "RISHAB": "RISHABH J",
    "RISHABH": "RISHABH J",
    "BHUVANESWARI": "BHUVANESHWARI A",
    "BHUVANESHWARI": "BHUVANESHWARI A",
    "SREEJITH": "SREEJITH K R",
    "ADITYA": "ADITYA KUMAR",
    "SUDIR": "SUDHIR POOJARY",
    "SUDHIR": "SUDHIR POOJARY",
    "LOKESH": "LOKESH REDDY K",
    "HANI": "HANI KRISHNA",
    "SANJEEV .": "SANJEEV",
}

# Rows on the target tabs that name a team manager or a roll-up, not a consultant.
TEAM_LABELS = {"PRINCE", "NETHRA", "NETRA", "ULLAS"}
NON_CONSULTANT_LABELS = {
    "TOTAL", "GRAND TOTAL", "WORKSHOP", "CO-DEALER", "WALKIN TEAM",
    "S/R TEAM (WALKIN, CRM & REFERRAL)", "FIELD TEAM (TELE & DIGITAL)",
}


def consultant_key(value) -> str | None:
    """Canonical upper-case consultant name, or None if the label is not a person."""
    name = upper(value)
    if not name:
        return None
    name = name.rstrip(".").strip()
    name = CONSULTANT_ALIASES.get(name, name)
    if name in TEAM_LABELS or name in NON_CONSULTANT_LABELS:
        return None
    if name.startswith(("S/R TEAM", "FIELD TEAM", "TOTAL")):
        return None
    return name


def team_key(value) -> str | None:
    """Canonical team name for a label that names a team."""
    name = upper(value)
    if not name:
        return None
    if name == "NETRA":
        name = "NETHRA"
    return name if name in {"PRINCE", "NETHRA", "ULLAS"} else None


# ---------------------------------------------------------------------
# Lead sources
# ---------------------------------------------------------------------

# The CRM export vocabulary and the DSR tab vocabulary describe the same channels.
# "Central Webin" is VW's central web-enquiry feed, which reaches the dealership
# through the CRM queue - the SC Performance roll-up calls that column CRM, and the
# two counts agree (160 leads), which is what justifies merging them.
SOURCE_MAP = {
    "WALK IN": ("WALKIN", "WALKIN", False),
    "WALKIN": ("WALKIN", "WALKIN", False),
    "TELE IN": ("TELE", "TELE", False),
    "TELE": ("TELE", "TELE", False),
    "TELEIN": ("TELE", "TELE", False),
    "DIGITAL": ("DIGITAL", "DIGITAL", True),
    "DIGI": ("DIGITAL", "DIGITAL", True),
    "CENTRAL WEBIN": ("CRM", "CRM", False),
    "CRM": ("CRM", "CRM", False),
    "CRM & OTHERS": ("CRM", "CRM", False),
    "CUSTOMER REFERRAL": ("REFERENCE", "REFERRAL", False),
    "REFERRAL": ("REFERENCE", "REFERRAL", False),
    "REFERENCE": ("REFERENCE", "REFERRAL", False),
    "SHOWROOM REFERRAL": ("SHOWROOM REFERRAL", "REFERRAL", False),
    "WORKSHOP REFERRAL": ("WORKSHOP REFERRAL", "WORKSHOP", False),
    "WORKSHOP": ("WORKSHOP REFERRAL", "WORKSHOP", False),
    "WS": ("WORKSHOP REFERRAL", "WORKSHOP", False),
    "EVENT": ("EVENT", "EVENT", False),
    "HYPERLOCAL": ("HYPERLOCAL", "HYPERLOCAL", True),
    "IPOPI": ("IPOPI", "HYPERLOCAL", True),
    "I POPI": ("IPOPI", "HYPERLOCAL", True),
    "REVSPOT": ("REVSPOT", "OTHER", True),
    "IVRS": ("IVRS", "TELE", False),
}


def source_key(value) -> tuple[str, str, bool] | None:
    """Returns (canonical_name, channel_group, is_paid_media) or None."""
    name = upper(value)
    if not name:
        return None
    if name in SOURCE_MAP:
        return SOURCE_MAP[name]
    return (name, "OTHER", False)


# ---------------------------------------------------------------------
# Models and variants
# ---------------------------------------------------------------------

# name -> (family, is_cbu). Facelift Taigun is kept as its own model because the
# DSR orders and reports stock against it separately, but shares the TAIGUN family
# so model-level totals still line up with the VW Report tab.
MODEL_MAP = {
    "TAIGUN": ("TAIGUN", False),
    "TAIGUN (FL)": ("TAIGUN", False),
    "VIRTUS": ("VIRTUS", False),
    "TAYRON": ("TAYRON", True),
    "TAYRON R-LINE 2.0": ("TAYRON", True),
    "GOLF GTI": ("GOLF", True),
    "TIGUAN R-LINE": ("TIGUAN", True),
    "TIGUAN R-LINE 2.0": ("TIGUAN", True),
}

# Longest first, so "TAIGUN (FL)" is tested before "TAIGUN".
_FAMILY_PATTERNS = [
    ("TIGUAN R-LINE", "TIGUAN R-LINE"),
    ("TAYRON", "TAYRON"),
    ("GOLF", "GOLF GTI"),
    ("VIRTUS", "VIRTUS"),
    ("TAIGUN", "TAIGUN"),
]


def model_key(value) -> str | None:
    """Canonical model name from an explicit model cell."""
    name = upper(value)
    if not name:
        return None
    name = name.replace("(FL )", "(FL)").replace("( FL)", "(FL)")
    return name


def model_from_text(value) -> str | None:
    """
    Guess the model from a factory description.

    "Virtus GT PLUS SPORT 1.5 TSI 110 kW DSG" -> VIRTUS. Used for leads and test
    drives, where the CRM only exports the long description and never the model.
    Cannot distinguish Taigun from the facelift, so it returns the base family.
    """
    text = upper(value)
    if not text:
        return None
    for needle, model in _FAMILY_PATTERNS:
        if needle in text:
            return model
    return None


def variant_key(value) -> str | None:
    """
    Canonical variant name.

    The sheets write the same trim as "GT Line AT", "GT LINE AT" and "GT LINE  AT".
    """
    name = upper(value)
    if not name:
        return None
    return re.sub(r"\s+", " ", name)


def transmission_of(variant_name: str | None) -> str | None:
    if not variant_name:
        return None
    name = variant_name.upper()
    if "DSG" in name:
        return "DSG"
    if name.endswith(" AT") or " AT " in name or name == "AT":
        return "AT"
    if name.endswith(" MT") or " MT " in name or name == "MT":
        return "MT"
    return None


def colour_key(value) -> str | None:
    """Colour names are kept as written (they are already consistent), just tidied."""
    text = clean(value)
    if not text:
        return None
    return re.sub(r"\s*/\s*", " / ", text)


# ---------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------

STOCK_STATUS_MAP = {
    "FREESTOCK": "FREESTOCK",
    "FREE STOCK": "FREESTOCK",
    "ALLOTED": "ALLOTED",
    "ALLOTTED": "ALLOTED",
    "RETAILED": "RETAILED",
    "REGISTERED": "REGISTERED",
}

FULFILMENT_STATUS_MAP = {
    "BOOKED": "BOOKED",
    "NO STOCK": "NO_STOCK",
    "NOSTOCK": "NO_STOCK",
    "ALLOTED": "ALLOTED",
    "ALLOTTED": "ALLOTED",
    "RETAILED": "RETAILED",
    "CANCELLED": "CANCELLED",
    "CANCELED": "CANCELLED",
}

CAR_ORIGIN_MAP = {
    "FRESH CAR": "FRESH_CAR",
    "PUNCHED CAR": "PUNCHED_CAR",
}


def stock_status(value) -> str | None:
    return STOCK_STATUS_MAP.get(upper(value) or "")


def fulfilment_status(value) -> str | None:
    return FULFILMENT_STATUS_MAP.get(upper(value) or "")


def car_origin(value) -> str | None:
    return CAR_ORIGIN_MAP.get(upper(value) or "")


def chassis(value) -> str | None:
    """A chassis number (VIN), or None when the cell holds something else.

    A chassis has no spaces: 10 to 20 letters and digits, with at least one of
    each. A September upload carried customers' names in the chassis column,
    and keyed on chassis that made a second "car" for every name - a hundred
    phantom units counted as stock."""
    text = (upper(value) or "").replace(" ", "")       # a stray space in a real chassis
    if text and re.fullmatch(r"[A-Z0-9]{10,20}", text) \
            and re.search(r"[0-9]", text) and re.search(r"[A-Z]", text):
        return text
    return None


def mobile(value) -> str | None:
    """Keep digits only, and drop anything that is not a plausible Indian mobile."""
    text = clean(value)
    if not text:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) > 10:
        digits = digits[-10:]
    return digits if len(digits) == 10 else None
