"""Text, number and unit normalization (handoff §15).

Every function here is independent and exactly tested. The original ``raw`` text
and its evidence are always retained separately; a normalized value never
replaces the source quote.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from decimal import Context, Decimal, InvalidOperation, localcontext
from typing import Optional

from .types import MAX_SAFE_INTEGER, NormalizedValue

VERSION = "normalization-1.0.0"

# Enough precision for aggregate sums of shipment masses without hidden rounding.
DECIMAL_CONTEXT = Context(prec=40)

_WHITESPACE = re.compile(r"\s+")

# Documented placeholder tokens meaning "no value supplied".
PLACEHOLDER_TOKENS = frozenset({
    "n/a", "na", "n.a.", "n/a.", "nil", "none", "-", "--", "---",
    "tba", "tbd", "tbc", "?", "n/k", "unknown",
})


# Typographic quote and prime characters. PDF text extraction commonly returns
# U+2019 where the source shows an ASCII apostrophe, as in ``40’HC``, and NFKC
# does not fold it.
_QUOTE_VARIANTS = str.maketrans({
    "\u2018": "'", "\u2019": "'", "\u201b": "'", "\u02bc": "'",
    "\u00b4": "'", "\u2032": "'", "\u0060": "'",
})


def canonicalize_quotes(text: str) -> str:
    """Fold typographic apostrophes and primes to the ASCII apostrophe."""
    return (text or "").translate(_QUOTE_VARIANTS)


def is_missing_value(raw: Optional[str]) -> bool:
    """True for an empty span or a documented placeholder.

    ``TO ORDER`` is legitimate text and is never treated as missing.
    """
    if raw is None:
        return True
    text = unicodedata.normalize("NFKC", raw).strip()
    if not text:
        return True
    if re.fullmatch(r"[_\s.\-–—*]+", text):
        return True
    return text.casefold() in PLACEHOLDER_TOKENS


# ---------------------------------------------------------------------------
# 15.1 Party blocks
# ---------------------------------------------------------------------------

def normalize_party(raw: str) -> str:
    """Case-folded, whitespace-collapsed full block.

    The complete labelled name and address are kept. Names are not reordered,
    legal-entity qualifiers are not dropped, "on behalf of" is not removed and
    no fuzzy similarity merges two companies. Only trailing separators are
    treated as insignificant punctuation.
    """
    text = unicodedata.normalize("NFKC", raw or "")
    text = text.replace(" ", " ")
    text = _WHITESPACE.sub(" ", text).strip()
    text = text.casefold()
    return text.strip(" ,;.")


# ---------------------------------------------------------------------------
# 15.2 Ports
# ---------------------------------------------------------------------------

# A small audited alias map. Entries are source-backed equivalences only; no
# pair-specific exception is ever added to make one case score better.
PORT_ALIASES: dict[str, str] = {}

_PORT_CODE = re.compile(r"\(([A-Z]{5})\)")
_ALTERNATIVES = re.compile(r"[A-Za-z]{2,}\s*/\s*[A-Za-z]{2,}")


def port_has_alternatives(raw: str) -> bool:
    """True for a value such as ``RUGAO/NANTONG/SHANGHAI``.

    The source expresses unresolved alternatives. They are recorded as a flag and
    never collapsed to whichever single port the other document happens to name.
    """
    return bool(_ALTERNATIVES.search(raw or ""))


def port_code(raw: str) -> Optional[str]:
    """A parenthesised five-letter UN/LOCODE, when the format rule matches."""
    match = _PORT_CODE.search(unicodedata.normalize("NFKC", raw or "").upper())
    return match.group(1) if match else None


def normalize_port(raw: str) -> str:
    """Case and space normalization plus the audited alias map.

    Parentheses are preserved: stripping them would lose terminal distinctions
    such as ``PORT KLANG (WESTPORT)``.
    """
    text = unicodedata.normalize("NFKC", raw or "")
    text = text.replace(" ", " ")
    text = _WHITESPACE.sub(" ", text).strip().casefold().strip(" ,;.")
    return PORT_ALIASES.get(text, text)


# ---------------------------------------------------------------------------
# 15.5 Numeric punctuation
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class NumberParse:
    """The outcome of interpreting one numeric token."""

    value: Optional[Decimal] = None
    ambiguous: bool = False
    reason: str = ""
    convention: str = ""          # "explicit", "grouping", "decimal", "plain"

    @property
    def ok(self) -> bool:
        return self.value is not None


_NUMBER_TOKEN = re.compile(r"[+-]?\d(?:[\d.,  ']*\d)?")
_GROUPED_3 = re.compile(r"^\d{1,3}(?:%s\d{3})+$")


def _digits_grouped(body: str, separator: str) -> bool:
    return re.fullmatch(r"\d{1,3}(?:" + re.escape(separator) + r"\d{3})+", body) is not None


def detect_document_convention(text: str) -> str:
    """Infer a document's separator convention from its own unambiguous numbers.

    Only notation that cannot mean anything else counts: a number carrying both
    separators, or one with two or more grouping separators. Returns ``"en"``,
    ``"eu"`` or ``""`` when the document supplies no independent evidence.
    """
    sample = unicodedata.normalize("NFKC", text or "")
    en = bool(re.search(r"\d{1,3}(?:,\d{3})+\.\d+", sample)) or \
        bool(re.search(r"\d{1,3}(?:,\d{3}){2,}(?!\d)", sample))
    eu = bool(re.search(r"\d{1,3}(?:\.\d{3})+,\d+", sample)) or \
        bool(re.search(r"\d{1,3}(?:\.\d{3}){2,}(?!\d)", sample))
    if en and not eu:
        return "en"
    if eu and not en:
        return "eu"
    return ""


# A registry-wide convention is adopted only on repeated, unambiguous evidence.
# One stray value is not a corpus convention.
REGISTRY_CONVENTION_MIN_EVIDENCE = 3


def detect_corpus_convention(texts, *, minimum: int = REGISTRY_CONVENTION_MIN_EVIDENCE) -> str:
    """Infer a source registry's separator convention from its own documents.

    Same evidence rule as :func:`detect_document_convention`, but counted across
    the registry and required to clear ``minimum`` distinct unambiguous values
    with no counter-evidence. Returns ``""`` when the registry does not establish
    a convention, which keeps a lone separator ambiguous.
    """
    en: set[str] = set()
    eu: set[str] = set()
    for text in texts:
        sample = unicodedata.normalize("NFKC", text or "")
        for pattern in (r"\d{1,3}(?:,\d{3})+\.\d+", r"\d{1,3}(?:,\d{3}){2,}(?!\d)"):
            en.update(match.group(0) for match in re.finditer(pattern, sample))
        for pattern in (r"\d{1,3}(?:\.\d{3})+,\d+", r"\d{1,3}(?:\.\d{3}){2,}(?!\d)"):
            eu.update(match.group(0) for match in re.finditer(pattern, sample))
    if en and eu:
        return ""  # contradictory evidence: stay conservative
    if len(en) >= minimum:
        return "en"
    if len(eu) >= minimum:
        return "eu"
    return ""


def parse_number(token: str, *, policy: str = "auto", convention: str = "") -> NumberParse:
    """Interpret a numeric token exactly, or report why it is ambiguous.

    ``policy`` is the configured locale policy; ``convention`` is the evidence
    found in the same document, used only when ``policy`` is ``"auto"``.
    """
    if token is None:
        return NumberParse(ambiguous=False, reason="EMPTY")
    text = unicodedata.normalize("NFKC", token).strip()
    text = text.replace(" ", "").replace("'", "").replace(" ", "")
    if not text:
        return NumberParse(reason="EMPTY")

    sign = ""
    if text[0] in "+-":
        sign, text = ("-" if text[0] == "-" else ""), text[1:]
    if not text or not re.fullmatch(r"[\d.,]+", text):
        return NumberParse(reason="NOT_NUMERIC")

    commas = text.count(",")
    dots = text.count(".")

    def build(body: str, fraction: str = "") -> NumberParse:
        literal = f"{sign}{body}" + (f".{fraction}" if fraction else "")
        try:
            with localcontext(DECIMAL_CONTEXT):
                return NumberParse(value=Decimal(literal), convention="explicit")
        except InvalidOperation:
            return NumberParse(reason="NOT_NUMERIC")

    if commas and dots:
        # The rightmost separator is the decimal mark; the other must group by 3.
        if text.rfind(",") > text.rfind("."):
            group_sep, decimal_sep = ".", ","
        else:
            group_sep, decimal_sep = ",", "."
        integer_part, _, fraction = text.rpartition(decimal_sep)
        if decimal_sep in integer_part or not fraction.isdigit():
            return NumberParse(reason="MALFORMED_SEPARATORS")
        if not _digits_grouped(integer_part, group_sep):
            return NumberParse(reason="MALFORMED_SEPARATORS")
        return build(integer_part.replace(group_sep, ""), fraction)

    separator = "," if commas else ("." if dots else "")
    if not separator:
        return build(text)

    count = commas or dots
    body_parts = text.split(separator)
    if count >= 2:
        if _digits_grouped(text, separator):
            return build(text.replace(separator, ""))
        return NumberParse(reason="MALFORMED_SEPARATORS")

    left, right = body_parts
    if not left.isdigit() or not right.isdigit():
        return NumberParse(reason="MALFORMED_SEPARATORS")
    if len(right) != 3:
        # Only a decimal separator can produce a non-three-digit tail.
        return build(left, right)

    # One separator with exactly three trailing digits: 1,234 could be 1234 or
    # 1.234. Resolve it only from an established convention, never by guessing
    # which reading matches the other document.
    effective = policy
    if policy == "auto":
        effective = convention or "ambiguous"
    if effective == "ambiguous":
        return NumberParse(
            ambiguous=True,
            reason="LONE_SEPARATOR_AMBIGUOUS",
            convention="",
        )
    grouping = "," if effective == "en" else "."
    if separator == grouping:
        result = build(left + right)
    else:
        result = build(left, right)
    return NumberParse(value=result.value, reason=result.reason, convention=effective) \
        if result.ok else result


# ---------------------------------------------------------------------------
# 15.3 Container count
# ---------------------------------------------------------------------------

# Container-type tokens that establish the value really counts containers.
CONTAINER_TYPE = re.compile(
    r"\b(\d{2})\s*'?\s*(HC|HQ|GP|DV|RF|RH|FR|OT|TK|FCL|STD)\b|\bFCL\b|\bTEU\b|\bFEU\b|\bCNTRS?\b|\bCONTAINERS?\b",
    re.IGNORECASE,
)
_COUNT_TERM = re.compile(
    r"(?P<count>\d{1,6})\s*[xX×*]\s*(?P<type>\d{2}\s*'?\s*[A-Za-z]{2,4}|[A-Za-z]{2,5})"
)


@dataclass(frozen=True)
class CountParse:
    value: Optional[int] = None
    terms: tuple[str, ...] = ()
    ambiguous: bool = False
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.value is not None


def parse_container_count(raw: str, *, label_is_ambiguous: bool = False) -> CountParse:
    """Derive a positive container count from a source value.

    ``3 x 40'HC`` is three containers; ``40`` is a size, never the count.
    Disjoint terms such as ``2 x 20GP + 1 x 40HC`` are summed with each term
    retained. Under a "Containers or Packages" heading, container-specific
    context is required so 500 packages never becomes 500 containers.
    """
    text = canonicalize_quotes(unicodedata.normalize("NFKC", raw or "")).strip()
    if not text:
        return CountParse(reason="EMPTY")

    terms = list(_COUNT_TERM.finditer(text))
    if terms:
        total = 0
        captured: list[str] = []
        for term in terms:
            count = int(term.group("count"))
            if count <= 0:
                return CountParse(reason="NON_POSITIVE")
            total += count
            captured.append(term.group(0))
        if total <= 0 or total > MAX_SAFE_INTEGER:
            return CountParse(reason="OUT_OF_RANGE")
        return CountParse(value=total, terms=tuple(captured))

    bare = re.fullmatch(r"(\d{1,6})(?:\s*(?:x|units?|pcs?))?", text, re.IGNORECASE)
    if bare:
        if label_is_ambiguous and not CONTAINER_TYPE.search(text):
            # "No. of Containers or Packages: 500" without container context.
            return CountParse(ambiguous=True, reason="NO_CONTAINER_CONTEXT")
        value = int(bare.group(1))
        if value <= 0:
            return CountParse(reason="NON_POSITIVE")
        if value > MAX_SAFE_INTEGER:
            return CountParse(reason="OUT_OF_RANGE")
        return CountParse(value=value, terms=(bare.group(0),))

    return CountParse(ambiguous=True, reason="UNRECOGNIZED_COUNT_FORMAT")


# ---------------------------------------------------------------------------
# 15.4 Gross weight
# ---------------------------------------------------------------------------

# Versioned unit table. Only verified conversions are listed. A bare "ton"
# remains ambiguous because it has no single convention.
UNIT_FACTORS: dict[str, Decimal] = {
    "kg": Decimal(1),
    "kgs": Decimal(1),
    "kgm": Decimal(1),
    "kilo": Decimal(1),
    "kilos": Decimal(1),
    "kilogram": Decimal(1),
    "kilograms": Decimal(1),
    "kilogramme": Decimal(1),
    "kilogrammes": Decimal(1),
    "mt": Decimal(1000),
    "mts": Decimal(1000),
    "tonne": Decimal(1000),
    "tonnes": Decimal(1000),
    "metricton": Decimal(1000),
    "metrictons": Decimal(1000),
    "metrictonne": Decimal(1000),
    "metrictonnes": Decimal(1000),
}

AMBIGUOUS_UNITS = frozenset({"t", "ton", "tons", "lb", "lbs", "pound", "pounds"})

_UNIT_TOKEN = re.compile(r"[A-Za-z][A-Za-z.\s]*$")


@dataclass(frozen=True)
class WeightParse:
    value: Optional[Decimal] = None     # always in kilograms
    unit: str = ""
    unit_from_label: bool = False
    ambiguous: bool = False
    reason: str = ""


def _canonical_unit(token: str) -> str:
    return re.sub(r"[.\s]", "", unicodedata.normalize("NFKC", token or "")).casefold()


def parse_gross_weight(raw: str, *, label: Optional[str] = None,
                       label_kg: bool = False, label_tonnes: bool = False,
                       policy: str = "auto", convention: str = "") -> WeightParse:
    """Derive a finite positive mass in kilograms, or say why it cannot be derived.

    A unit must come from the value or from the field/column heading. The
    internal field name ``gross_weight_kg`` never supplies a missing unit.
    """
    text = unicodedata.normalize("NFKC", raw or "").strip()
    if not text:
        return WeightParse(reason="EMPTY")

    match = _NUMBER_TOKEN.search(text)
    if match is None:
        return WeightParse(reason="NO_NUMBER")
    number_text = match.group(0)
    remainder = (text[:match.start()] + " " + text[match.end():]).strip()

    parsed = parse_number(number_text, policy=policy, convention=convention)
    if parsed.ambiguous:
        return WeightParse(ambiguous=True, reason=parsed.reason)
    if not parsed.ok:
        return WeightParse(reason=parsed.reason or "NOT_NUMERIC")
    magnitude = parsed.value
    assert magnitude is not None

    unit_token = ""
    unit_match = _UNIT_TOKEN.search(remainder)
    if unit_match:
        unit_token = _canonical_unit(unit_match.group(0))

    unit_from_label = False
    if unit_token in UNIT_FACTORS:
        factor = UNIT_FACTORS[unit_token]
    elif unit_token in AMBIGUOUS_UNITS:
        return WeightParse(ambiguous=True, unit=unit_token, reason="AMBIGUOUS_UNIT")
    elif unit_token:
        return WeightParse(ambiguous=True, unit=unit_token, reason="UNKNOWN_UNIT")
    elif label_kg:
        factor, unit_from_label, unit_token = Decimal(1), True, "kg"
    elif label_tonnes:
        factor, unit_from_label, unit_token = Decimal(1000), True, "mt"
    else:
        # No unit in the value and none in the heading.
        return WeightParse(ambiguous=True, reason="MISSING_UNIT")

    with localcontext(DECIMAL_CONTEXT):
        kilograms = magnitude * factor

    if not kilograms.is_finite():
        return WeightParse(reason="NOT_FINITE")
    if kilograms <= 0:
        return WeightParse(reason="NON_POSITIVE")
    if kilograms > Decimal(MAX_SAFE_INTEGER):
        return WeightParse(reason="OUT_OF_RANGE")

    return WeightParse(value=kilograms, unit=unit_token, unit_from_label=unit_from_label)


# ---------------------------------------------------------------------------
# Canonical value construction
# ---------------------------------------------------------------------------

def normalized_for_field(field: str, raw: str, **kwargs) -> Optional[NormalizedValue]:
    """Build the canonical comparison value for a field, or ``None``."""
    if field in ("shipper", "consignee", "notify_party"):
        text = normalize_party(raw)
        return NormalizedValue.of_text(text) if text else None
    if field in ("port_of_loading", "port_of_discharge"):
        text = normalize_port(raw)
        return NormalizedValue.of_text(text) if text else None
    if field == "container_count":
        parsed = parse_container_count(raw, **kwargs)
        return NormalizedValue.of_integer(Decimal(parsed.value)) if parsed.ok else None
    if field == "gross_weight_kg":
        parsed = parse_gross_weight(raw, **kwargs)
        return NormalizedValue.of_decimal(parsed.value) if parsed.value is not None else None
    return None
