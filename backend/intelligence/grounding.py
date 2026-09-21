"""G1/G2/G3 — one implementation for every path that produces a value.

Machine extraction, AI extraction, human document-confirmed entry and candidate
selection all pass through :func:`ground_candidate`. A caller can never assert
``grounded=True`` as evidence; the gates decide.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Optional

from .normalization import (
    detect_document_convention,
    normalize_party,
    normalize_port,
    parse_container_count,
    parse_gross_weight,
)
from .policies import aliases
from .types import (
    Candidate,
    Derivation,
    Evidence,
    GroundingResult,
    NormalizedValue,
    NUMERIC_FIELDS,
    PARTY_FIELDS,
    PORT_FIELDS,
    ParsedDocument,
    ParseStatus,
)

VERSION = "grounding-1.0.0"


# ---------------------------------------------------------------------------
# G1 — source existence
# ---------------------------------------------------------------------------

def _block_locators(block) -> tuple:
    """Every locator that addresses part of this block's value."""
    return (block.value_locator,) + tuple(block.extra_value_locators)


def _block_texts(block) -> tuple[str, ...]:
    """Every persisted text this block's value spans."""
    extra = tuple(block.context.get("extra_value_texts") or ())
    return (block.value_text,) + extra


def check_g1(candidate: Candidate, document: ParsedDocument, *,
             expected_hash: Optional[str] = None) -> GroundingResult:
    """The exact quote occurs at the bound block's location in this run's artifact.

    The candidate must name the private parser block it was read from. Verifying
    against the *page* is not enough: every value on a PDF page shares
    ``PdfPage(1)``, so a page-level check would accept one field's number as
    another field's value. A fabricated quote, a wrong page, a stale artifact
    hash, another document or an out-of-bounds location all fail.
    """
    if document.status is not ParseStatus.OK:
        return GroundingResult.fail("G1", "DOCUMENT_NOT_PARSED",
                                    f"document status is {document.status.value}")
    if candidate.document_id != document.document_id:
        return GroundingResult.fail("G1", "WRONG_DOCUMENT",
                                    f"candidate names {candidate.document_id!r}, "
                                    f"artifact is {document.document_id!r}")
    if expected_hash is not None and document.content_hash != expected_hash:
        return GroundingResult.fail("G1", "STALE_ARTIFACT",
                                    "the parsed artifact does not match this run's input hash")
    if not candidate.evidence:
        return GroundingResult.fail("G1", "NO_EVIDENCE", "the candidate carries no evidence")

    block = document.block_by_id(candidate.block_id)
    if block is None:
        return GroundingResult.fail(
            "G1", "NO_BOUND_BLOCK",
            "the candidate is not bound to a structural block in this artifact",
        )

    primary = candidate.evidence[0]
    if primary.document_id != document.document_id:
        return GroundingResult.fail("G1", "EVIDENCE_OUTSIDE_DOCUMENT",
                                    f"evidence names {primary.document_id!r}")
    if primary.locator not in _block_locators(block):
        return GroundingResult.fail(
            "G1", "EVIDENCE_NOT_IN_BOUND_BLOCK",
            "the primary evidence does not address the bound block's value",
        )

    block_texts = _block_texts(block)
    if not _quote_supported(primary.source_text, primary.locator, block_texts):
        return GroundingResult.fail(
            "G1", "QUOTE_MISMATCH",
            "the quote is not the text stored at the bound block's value location",
        )

    # Secondary evidence (a contributing cell, or the referenced consignee block)
    # must also resolve to a real block's value in this same document.
    reference_block = document.block_by_id(candidate.reference_block_id)
    allowed = list(block_texts)
    if reference_block is not None:
        allowed.extend(_block_texts(reference_block))
    for extra in candidate.evidence[1:]:
        if extra.document_id != document.document_id:
            return GroundingResult.fail("G1", "EVIDENCE_OUTSIDE_DOCUMENT",
                                        f"evidence names {extra.document_id!r}")
        if not _quote_supported(extra.source_text, extra.locator, tuple(allowed)):
            return GroundingResult.fail(
                "G1", "SUPPORTING_QUOTE_MISMATCH",
                "a supporting quote does not occur in the bound or referenced block",
            )
    return GroundingResult.ok()


def _quote_supported(quote: str, locator, texts: tuple[str, ...]) -> bool:
    """Whether ``quote`` is the stored text, allowing a part of a multi-line span.

    An exact locator must match exactly. A container locator (page, paragraph,
    table cell, sheet cell) may hold a multi-line value, so a quote of one line
    of the bound block's own value is accepted — but only of that block's value.
    """
    if ParsedDocument.locator_is_exact(locator):
        return quote in texts
    if not quote.strip():
        return False
    return any(quote == text or quote in text for text in texts)


# ---------------------------------------------------------------------------
# G2 — field context
# ---------------------------------------------------------------------------

def check_g2(candidate: Candidate, document: ParsedDocument) -> GroundingResult:
    """The bound block's own label supports this canonical field.

    The label is read from the artifact, never from the candidate: a candidate
    that simply claims ``label_text="Gross Weight"`` proves nothing. A gross
    weight is therefore never supported by digits sitting in a seal number, a
    net weight or an invoice amount, and a party value must come from that
    party's own labelled block.
    """
    block = document.block_by_id(candidate.block_id)
    if block is None:
        return GroundingResult.fail("G2", "NO_BOUND_BLOCK",
                                    "the candidate is not bound to a structural block")

    if candidate.derivation is Derivation.REFERENCE:
        # "Same as consignee" is supported by the reference wording in its own
        # notify-party block plus that side's consignee block.
        if candidate.reference_field != "consignee":
            return GroundingResult.fail("G2", "UNSUPPORTED_REFERENCE",
                                        f"unknown reference target {candidate.reference_field!r}")
        if aliases.match_field(block.label) != "notify_party":
            return GroundingResult.fail(
                "G2", "LABEL_DOES_NOT_SUPPORT_FIELD",
                f"block label {block.label!r} does not label a notify party")
        reference_block = document.block_by_id(candidate.reference_block_id)
        if reference_block is None:
            return GroundingResult.fail("G2", "REFERENCE_BLOCK_MISSING",
                                        "the referenced consignee block is not bound")
        if aliases.match_field(reference_block.label) != "consignee":
            return GroundingResult.fail(
                "G2", "REFERENCE_LABEL_MISMATCH",
                f"referenced block label {reference_block.label!r} is not a consignee")
        return GroundingResult.ok()

    if not block.label:
        return GroundingResult.fail("G2", "NO_LABEL",
                                    "the bound block has no label supporting the field")
    if aliases.label_is_negative_for(candidate.field, block.label):
        return GroundingResult.fail(
            "G2", "NEGATIVE_LABEL",
            f"block label {block.label!r} is a known wrong source for {candidate.field}")
    resolved = aliases.match_field(block.label)
    if resolved != candidate.field:
        return GroundingResult.fail(
            "G2", "LABEL_DOES_NOT_SUPPORT_FIELD",
            f"block label {block.label!r} resolves to {resolved!r}, not {candidate.field!r}",
        )

    if candidate.field == "gross_weight_kg" and "UNIT_FROM_LABEL" in candidate.flags:
        if candidate.unit_evidence is None:
            return GroundingResult.fail("G2", "UNIT_EVIDENCE_MISSING",
                                        "the unit came from the heading but its evidence is absent")
        if not (aliases.label_declares_kg(block.label)
                or aliases.label_declares_tonnes(block.label)):
            return GroundingResult.fail(
                "G2", "UNIT_NOT_IN_LABEL",
                f"block label {block.label!r} does not declare the unit that was used")
    return GroundingResult.ok()


# ---------------------------------------------------------------------------
# G3 — deterministic derivation
# ---------------------------------------------------------------------------

def check_g3(candidate: Candidate, document: ParsedDocument, *,
             policy: str = "auto",
             fallback_convention: str = "",
             reference_values: Optional[Mapping[str, NormalizedValue]] = None) -> GroundingResult:
    """Re-derive the proposed value from the evidence and require an exact match.

    The proposal is recomputed independently: it is not trusted because it was
    produced earlier by the same code path, and never because a model asserted it.
    """
    proposed = candidate.normalized
    if proposed is None:
        return GroundingResult.fail("G3", "NO_NORMALIZED_VALUE", "no canonical value was proposed")

    if candidate.derivation is Derivation.REFERENCE:
        target = (reference_values or {}).get(candidate.reference_field or "")
        if target is None:
            return GroundingResult.fail("G3", "REFERENCE_TARGET_MISSING",
                                        "the referenced same-side value is not available")
        if not proposed.equals(target):
            return GroundingResult.fail("G3", "REFERENCE_MISMATCH",
                                        "the derived value differs from the referenced value")
        return GroundingResult.ok()

    # Re-derive from the bound block's own stored value, not from the quote the
    # candidate supplied: a caller must not be able to choose the text its value
    # is checked against.
    block = document.block_by_id(candidate.block_id)
    if block is None:
        return GroundingResult.fail("G3", "NO_BOUND_BLOCK",
                                    "the candidate is not bound to a structural block")
    source_text = block.value_text
    label_text = block.label
    # Same convention resolution extraction used: the document's own evidence
    # first, then the registry's. Re-deriving without the registry convention
    # would reject a value extraction had legitimately resolved.
    convention = detect_document_convention(document.text) or fallback_convention

    if candidate.field in PARTY_FIELDS:
        derived = normalize_party(source_text)
        if proposed.text != derived:
            return GroundingResult.fail("G3", "PARTY_DERIVATION_MISMATCH",
                                        "the normalized party block differs from the evidence")
        return GroundingResult.ok()

    if candidate.field in PORT_FIELDS:
        derived = normalize_port(source_text)
        if proposed.text != derived:
            return GroundingResult.fail("G3", "PORT_DERIVATION_MISMATCH",
                                        "the normalized port differs from the evidence")
        return GroundingResult.ok()

    if candidate.field == "container_count":
        parsed = parse_container_count(
            source_text,
            label_is_ambiguous=aliases.is_ambiguous_count_label(label_text),
        )
        if not parsed.ok:
            return GroundingResult.fail("G3", "COUNT_NOT_DERIVABLE",
                                        f"the evidence does not yield a count ({parsed.reason})")
        if Decimal(parsed.value) != proposed.number:
            return GroundingResult.fail("G3", "COUNT_MISMATCH",
                                        "the recomputed count differs from the proposal")
        if parsed.value <= 0:
            return GroundingResult.fail("G3", "NON_POSITIVE", "a container count must be positive")
        return GroundingResult.ok()

    if candidate.field == "gross_weight_kg":
        parsed = parse_gross_weight(
            source_text,
            label=label_text,
            label_kg=aliases.label_declares_kg(label_text),
            label_tonnes=aliases.label_declares_tonnes(label_text),
            policy=policy,
            convention=convention,
        )
        if parsed.value is None:
            return GroundingResult.fail("G3", "WEIGHT_NOT_DERIVABLE",
                                        f"the evidence does not yield a mass ({parsed.reason})")
        if parsed.value != proposed.number:
            return GroundingResult.fail("G3", "WEIGHT_MISMATCH",
                                        "the recomputed mass differs from the proposal")
        return GroundingResult.ok()

    return GroundingResult.fail("G3", "UNKNOWN_FIELD", f"no derivation rule for {candidate.field!r}")


def ground_candidate(candidate: Candidate, document: ParsedDocument, *,
                     policy: str = "auto",
                     fallback_convention: str = "",
                     expected_hash: Optional[str] = None,
                     reference_values: Optional[Mapping[str, NormalizedValue]] = None
                     ) -> GroundingResult:
    """Run all three gates in order, stopping at the first failure.

    The gates are evaluated lazily: a candidate that fails G1 is never passed to
    G2, which may legitimately assume the evidence G1 has already validated.
    """
    result = check_g1(candidate, document, expected_hash=expected_hash)
    if not result.passed:
        return result
    result = check_g2(candidate, document)
    if not result.passed:
        return result
    return check_g3(candidate, document, policy=policy,
                    fallback_convention=fallback_convention,
                    reference_values=reference_values)
