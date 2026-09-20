"""Port comparison policy (``ports-1.0.0``).

A parenthesised five-letter token is treated as a UN/LOCODE only under a
validated rule: its two-letter country prefix must match a country actually
named in the same value. That validation matters, because the corpus contains
values whose code contradicts the port — ``BALTIMORE, US (NGAPP)`` names a
Nigerian code against a US port. Such a code is a substantive difference and is
never discarded; a *consistent* code is supplementary formatting and may be set
aside when comparing two spellings of the same port.

No pair-specific exception is ever added here to improve a score.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

VERSION = "ports-1.0.0"

# Country names appearing in source port values, with their ISO 3166-1 alpha-2
# codes. Extending this table is a versioned policy change.
COUNTRY_ALPHA2: dict[str, str] = {
    "australia": "AU",
    "chile": "CL",
    "china": "CN",
    "guinea": "GN",
    "india": "IN",
    "indonesia": "ID",
    "israel": "IL",
    "jordan": "JO",
    "kenya": "KE",
    "lithuania": "LT",
    "malaysia": "MY",
    "myanmar": "MM",
    "nigeria": "NG",
    "pakistan": "PK",
    "peru": "PE",
    "philippines": "PH",
    "poland": "PL",
    "singapore": "SG",
    "slovenia": "SI",
    "south korea": "KR",
    "korea": "KR",
    "turkey": "TR",
    "uae": "AE",
    "united arab emirates": "AE",
    "us": "US",
    "usa": "US",
    "united states": "US",
    "vietnam": "VN",
    "viet nam": "VN",
}

ABSENT = "absent"
CONSISTENT = "consistent"
INCONSISTENT = "inconsistent"

_CODE = re.compile(r"\(([A-Za-z]{5})\)")
_WHITESPACE = re.compile(r"\s+")


def _normalize(raw: str) -> str:
    text = unicodedata.normalize("NFKC", raw or "").replace(" ", " ")
    return _WHITESPACE.sub(" ", text).strip().casefold().strip(" ,;.")


def extract_code(raw: str) -> Optional[str]:
    """The parenthesised five-letter token, upper-cased, if present."""
    match = _CODE.search(unicodedata.normalize("NFKC", raw or ""))
    return match.group(1).upper() if match else None


def named_countries(raw: str) -> frozenset[str]:
    """Alpha-2 codes for country names present as whole tokens in the value."""
    text = _normalize(raw)
    tokens = {part.strip() for part in re.split(r"[,/()]", text) if part.strip()}
    found = set()
    for name, alpha2 in COUNTRY_ALPHA2.items():
        if name in tokens:
            found.add(alpha2)
    return frozenset(found)


def code_consistency(raw: str) -> str:
    """``absent``, ``consistent`` or ``inconsistent`` for this value's port code."""
    code = extract_code(raw)
    if code is None:
        return ABSENT
    countries = named_countries(raw)
    if not countries:
        # No country is named, so the code cannot be validated either way.
        return INCONSISTENT
    return CONSISTENT if code[:2] in countries else INCONSISTENT


def supplementary_key(raw: str) -> Optional[str]:
    """The value with a *validated* code removed, or ``None`` when it is not validated.

    Returning ``None`` means the code carries meaning and full-string equality is
    the only comparison allowed.
    """
    state = code_consistency(raw)
    if state == INCONSISTENT:
        return None
    if state == ABSENT:
        return _normalize(raw)
    return _normalize(_CODE.sub(" ", raw))


def equal(left: str, right: str) -> bool:
    """Exact equality, allowing only a validated supplementary code to differ."""
    if _normalize(left) == _normalize(right):
        return True
    left_key = supplementary_key(left)
    right_key = supplementary_key(right)
    if left_key is None or right_key is None:
        return False
    if left_key != right_key:
        return False
    left_code = extract_code(left)
    right_code = extract_code(right)
    # Both validated: the codes must still agree when both are present.
    if left_code and right_code and left_code != right_code:
        return False
    return True
