"""Versioned label aliases for the seven canonical fields (policy ``aliases-1.0.0``).

The entries were taken from labels that actually occur in the source corpus.
Matching rules:

* Labels are compared after Unicode NFKC normalization, case folding and
  whitespace collapse, with a bilingual qualifier such as ``毛重`` or a
  parenthesised qualifier removed only when the remainder still matches.
* The longest, most specific alias wins, so ``Notify Party/Intermediate
  Consignee`` never resolves as ``Consignee``.
* ``NEGATIVE_LABELS`` are labels that must never supply a canonical field even
  though they contain a canonical word — a net weight is not a gross weight.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

VERSION = "aliases-1.0.0"

# Canonical field -> the exact labels observed in the corpus.
FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "shipper": (
        "shipper",
        "shipper/exporter",
        "shipper (principal or seller)",
        "shipper (principal/seller)",
        "exporter",
    ),
    "consignee": (
        "consignee",
        "consignee (non-negotiable)",
        "consignee (non negotiable)",
        "to the order of",
        "to order of",
    ),
    "notify_party": (
        "notify",
        "notify party",
        "notify party/intermediate consignee",
        "notify party / intermediate consignee",
        "intermediate consignee",
    ),
    "port_of_loading": (
        "port of loading",
        "port of loading (pol)",
        "load port",
        "loading port",
        "pol",
    ),
    "port_of_discharge": (
        "port of discharge",
        "port of discharge (pod)",
        "discharge port",
        "pod",
    ),
    "container_count": (
        "container count",
        "total containers",
        "no. of containers",
        "no of containers",
        "number of containers",
        "no. of containers or packages",
        "no of containers or packages",
        "containers or packages",
    ),
    "gross_weight_kg": (
        "gross weight",
        "gross weight (kg)",
        "gross weight (kgs)",
        "gross wt",
        "gross wt (kg)",
        "gross wt (kgs)",
        "gross weight(kgs)",
        "total gross weight",
        "total gross weight (kg)",
        "total gross weight (kgs)",
        "gross weight total",
    ),
}

# Labels whose canonical word must not be followed to a canonical field.
NEGATIVE_LABELS: dict[str, tuple[str, ...]] = {
    "gross_weight_kg": (
        "net weight",
        "net wt",
        "nett weight",
        "tare weight",
        "weight per container",
        "unit weight",
        "invoice amount",
        "total amount",
        "seal no",
        "seal number",
        "container no",
        "container number",
    ),
    "container_count": (
        "packages",
        "no. of packages",
        "kinds of packages",
        "package count",
        "container no",
        "container number",
        "seal no",
    ),
}

# Labels that establish the ambiguous "containers or packages" heading. A value
# under one of these needs container-specific context before it becomes a count.
AMBIGUOUS_COUNT_LABELS = frozenset({
    "no. of containers or packages",
    "no of containers or packages",
    "containers or packages",
})

# Labels that declare an explicit aggregate total rather than a detail row.
TOTAL_LABEL_MARKERS = ("total", "aggregate", "sum")

_WHITESPACE = re.compile(r"\s+")
_PARENTHETICAL = re.compile(r"\s*\([^)]*\)")
_CJK = re.compile(r"[　-鿿豈-﫿＀-￯]+")


def normalize_label(label: str) -> str:
    """NFKC, case-fold, collapse whitespace and drop trailing punctuation."""
    text = unicodedata.normalize("NFKC", label or "")
    text = text.casefold().strip()
    text = _WHITESPACE.sub(" ", text)
    return text.strip(" .:;-")


def _label_variants(label: str) -> tuple[str, ...]:
    """The normalized label plus the forms produced by dropping qualifiers.

    ``Gross Weight毛重(KGS) (毛重 KGS)`` yields ``gross weight(kgs)``,
    ``gross weight`` and so on, so a bilingual label resolves explicitly rather
    than by substring luck.
    """
    base = normalize_label(label)
    variants = [base]
    without_cjk = normalize_label(_CJK.sub("", base))
    if without_cjk and without_cjk != base:
        variants.append(without_cjk)
    for candidate in list(variants):
        stripped = normalize_label(_PARENTHETICAL.sub("", candidate))
        if stripped and stripped not in variants:
            variants.append(stripped)
    # Collapse "gross weight(kgs)" -> "gross weight (kgs)" spacing differences.
    spaced = [normalize_label(v.replace("(", " (")) for v in variants]
    for candidate in spaced:
        if candidate and candidate not in variants:
            variants.append(candidate)
    return tuple(dict.fromkeys(v for v in variants if v))


def match_field(label: Optional[str]) -> Optional[str]:
    """Resolve a source label to a canonical field, or ``None``.

    Longest alias first, so a more specific label never loses to a shorter one.
    """
    if not label:
        return None
    variants = _label_variants(label)

    # An explicit alias is the authority: "No. of Containers or Packages" is a
    # listed container_count alias even though "packages" is a negative marker.
    best: Optional[tuple[int, str]] = None
    for field, aliases in FIELD_ALIASES.items():
        for alias in aliases:
            if alias in variants:
                score = len(alias)
                if best is None or score > best[0]:
                    best = (score, field)
    if best is not None:
        return best[1]

    # No exact alias. A label carrying a negative marker must not be resolved by
    # any looser rule added later, so it is refused explicitly.
    for negatives in NEGATIVE_LABELS.values():
        if any(negative in variant for negative in negatives for variant in variants):
            return None
    return None


def label_is_negative_for(field: str, label: Optional[str]) -> bool:
    """True when ``label`` is a known wrong source for ``field``.

    G2 uses this to refuse a gross-weight proposal supported only by a net-weight,
    seal-number or invoice-amount label.
    """
    variants = _label_variants(label or "")
    negatives = NEGATIVE_LABELS.get(field, ())
    if any(negative in variant for negative in negatives for variant in variants):
        # Unless the label is itself an explicit alias for that field.
        return not any(alias in variants for alias in FIELD_ALIASES.get(field, ()))
    return False


def is_ambiguous_count_label(label: Optional[str]) -> bool:
    return any(variant in AMBIGUOUS_COUNT_LABELS for variant in _label_variants(label or ""))


def is_total_label(label: Optional[str]) -> bool:
    variants = _label_variants(label or "")
    return any(marker in variant for variant in variants for marker in TOTAL_LABEL_MARKERS)


def label_declares_kg(label: Optional[str]) -> bool:
    """True when the label itself supplies the kilogram unit, e.g. ``Gross Wt (kgs)``."""
    variants = _label_variants(label or "")
    return any(
        re.search(r"\b(kg|kgs|kilogram|kilograms|kilogramme|kilogrammes)\b", variant)
        for variant in variants
    )


def label_declares_tonnes(label: Optional[str]) -> bool:
    variants = _label_variants(label or "")
    return any(
        re.search(r"\b(mt|mts|metric ton|metric tons|metric tonne|metric tonnes|tonne|tonnes)\b",
                  variant)
        for variant in variants
    )
