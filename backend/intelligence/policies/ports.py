"""Port comparison policy (``ports-2.0.0``).

A parenthesised five-letter token is treated as a supplementary UN/LOCODE only
when :data:`VERIFIED_PORT_CODES` establishes that it identifies that port. That
table is derived from repeated evidence in the source registry by
``scripts/derive_port_codes.py``; it is not hand-tuned per case.

Country agreement alone is **not** proof. ``PORT KLANG, MALAYSIA (MYZZZ)`` has a
Malaysian prefix but names no verified port, so the code carries meaning and is
never discarded — otherwise a wrong same-country code appearing on one document
would silently vanish.

Three outcomes:

``verified``
    the code is the one this port is repeatedly recorded with, so two spellings
    that differ only by its presence compare equal.
``contradicted``
    the port is known and this is not its code, which is a real difference.
``unverified``
    nothing establishes this code, so the difference is preserved.

No pair-specific exception is ever added here to improve a score.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

VERSION = "ports-2.0.0"

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
VERIFIED = "verified"
CONTRADICTED = "contradicted"
UNVERIFIED = "unverified"

# Retained so existing callers keep working; ``consistent`` now means verified.
CONSISTENT = VERIFIED
INCONSISTENT = CONTRADICTED

# Source-backed port/code evidence. Regenerate with:
#   python scripts/derive_port_codes.py --source <registry> --emit-python
# A pair is listed only when it is the strict majority reading for that port and
# occurs at least three times. Ports whose evidence is split or thin (cebu,
# tuticorin, "singapore, singapore") are deliberately absent, so their codes stay
# unverified and any difference is preserved.
VERIFIED_PORT_CODES = {
    "apapa, nigeria": "NGAPP",                          # 10 observations
    "aqaba, jordan": "JOAQB",                           # 3 observations
    "ashdod, israel": "ILASH",                          # 7 observations
    "baltimore, us": "USBAL",                           # 4 observations
    "brisbane, australia": "AUBNE",                     # 7 observations
    "buatan, indonesia": "IDBUA",                       # 24 observations
    "busan, south korea": "KRPUS",                      # 3 observations
    "callao, peru": "PECLL",                            # 18 observations
    "conakry, guinea": "GNCKY",                         # 10 observations
    "fremantle, australia": "AUFRE",                    # 5 observations
    "gdansk, poland": "PLGDN",                          # 10 observations
    "hochiminh city, vietnam": "VNSGN",                 # 6 observations
    "houston, us": "USHOU",                             # 5 observations
    "jebel ali, uae": "AEJEA",                          # 4 observations
    "karachi, pakistan": "PKKHI",                       # 6 observations
    "klaipeda, lithuania": "LTKLJ",                     # 8 observations
    "koper, slovenia": "SIKOP",                         # 8 observations
    "long beach, us": "USLGB",                          # 6 observations
    "mersin, turkey": "TRMER",                          # 13 observations
    "mombasa, kenya": "KEMBA",                          # 5 observations
    "nantong, china": "CNNTG",                          # 36 observations
    "new york, us": "USNYC",                            # 7 observations
    "nhava sheva, india": "INNSA",                      # 27 observations
    "port klang (westport), malaysia": "MYPKG",         # 46 observations
    "pyeongtaek, south korea": "KRPTK",                 # 5 observations
    "rugao/nantong/shanghai, china": "CNSHA",           # 21 observations
    "savannah, us": "USSAV",                            # 8 observations
    "singapore": "SGSIN",                               # 23 observations
    "valparaiso, chile": "CLVAP",                       # 5 observations
    "yangon, myanmar": "MMRGN",                         # 7 observations
}


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


def code_state(raw: str) -> str:
    """``absent``, ``verified``, ``contradicted`` or ``unverified``."""
    code = extract_code(raw)
    if code is None:
        return ABSENT
    place = _normalize(_CODE.sub(" ", raw))
    expected = VERIFIED_PORT_CODES.get(place)
    if expected is None:
        # Nothing establishes what this port's code should be.
        return UNVERIFIED
    return VERIFIED if code == expected else CONTRADICTED


def code_consistency(raw: str) -> str:
    """Backwards-compatible alias for :func:`code_state`."""
    return code_state(raw)


def supplementary_key(raw: str) -> Optional[str]:
    """The value with a *verified* code removed, or ``None``.

    ``None`` means the code has not been established as this port's, so it
    carries meaning and full-string equality is the only comparison allowed.
    """
    state = code_state(raw)
    if state == ABSENT:
        return _normalize(raw)
    if state == VERIFIED:
        return _normalize(_CODE.sub(" ", raw))
    return None


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
