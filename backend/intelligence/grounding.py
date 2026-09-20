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

def check_g1(candidate: Candidate, document: ParsedDocument, *,
             expected_hash: Optional[str] = None) -> GroundingResult:
    """The exact quote occurs at that location in this run's parsed artifact.

    A fabricated quote, a wrong page, a stale artifact hash, another document or
    an out-of-bounds location all fail.
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

    for reference in candidate.evidence:
        if reference.document_id != document.document_id:
            # Evidence may legitimately span the same side's other field (a
            # "same as consignee" reference), but not another document.
            return GroundingResult.fail("G1", "EVIDENCE_OUTSIDE_DOCUMENT",
                                        f"evidence names {reference.document_id!r}")
        texts = document.locator_texts(reference.locator)
        if not texts:
            return GroundingResult.fail("G1", "LOCATOR_NOT_FOUND",
                                        f"{reference.locator!r} addresses nothing in the artifact")
        if ParsedDocument.locator_is_exact(reference.locator):
            if reference.source_text not in texts:
                return GroundingResult.fail("G1", "QUOTE_MISMATCH",
                                            "the quote is not the text stored at that location")
        else:
            if not reference.source_text.strip():
                return GroundingResult.fail("G1", "EMPTY_QUOTE",
                                            "an empty quote cannot be grounded in a container locator")
            if not any(reference.source_text in text for text in texts):
                return GroundingResult.fail("G1", "QUOTE_NOT_ON_PAGE",
                                            "the quote does not occur at that location")
    return GroundingResult.ok()


# ---------------------------------------------------------------------------
# G2 — field context
# ---------------------------------------------------------------------------

def check_g2(candidate: Candidate, document: ParsedDocument) -> GroundingResult:
    """The structural label relationship supports this canonical field.

    A gross-weight proposal cannot be supported only by equal digits sitting in a
    seal, booking, invoice-amount, net-weight or container-number field, and a
    party value must come from that party's own labelled block.
    """
    label = candidate.label_text
    if candidate.derivation is Derivation.REFERENCE:
        # "Same as consignee" is supported by the reference wording plus the
        # same side's consignee evidence.
        if candidate.reference_field != "consignee":
            return GroundingResult.fail("G2", "UNSUPPORTED_REFERENCE",
                                        f"unknown reference target {candidate.reference_field!r}")
        if aliases.match_field(label) != "notify_party":
            return GroundingResult.fail("G2", "LABEL_DOES_NOT_SUPPORT_FIELD",
                                        f"label {label!r} does not label a notify party")
        return GroundingResult.ok()

    if not candidate.evidence:
        return GroundingResult.fail("G2", "NO_EVIDENCE",
                                    "the candidate carries no evidence to relate to a label")
    if not label:
        return GroundingResult.fail("G2", "NO_LABEL",
                                    "the value has no structural label supporting the field")
    if aliases.label_is_negative_for(candidate.field, label):
        return GroundingResult.fail("G2", "NEGATIVE_LABEL",
                                    f"label {label!r} is a known wrong source for {candidate.field}")
    resolved = aliases.match_field(label)
    if resolved != candidate.field:
        return GroundingResult.fail(
            "G2", "LABEL_DOES_NOT_SUPPORT_FIELD",
            f"label {label!r} resolves to {resolved!r}, not {candidate.field!r}",
        )

    # The label must actually be a label in this artifact, related to the value
    # by preserved structure rather than proximity in a flattened document.
    related = any(
        block.label == label and (
            block.value_locator == candidate.evidence[0].locator
            or candidate.evidence[0].locator in block.extra_value_locators
        )
        for block in document.blocks
    )
    if not related:
        return GroundingResult.fail("G2", "LABEL_NOT_STRUCTURALLY_RELATED",
                                    "the label and value are not related by document structure")

    if candidate.field == "gross_weight_kg" and "UNIT_FROM_LABEL" in candidate.flags:
        if candidate.unit_evidence is None:
            return GroundingResult.fail("G2", "UNIT_EVIDENCE_MISSING",
                                        "the unit came from the heading but its evidence is absent")
    return GroundingResult.ok()


# ---------------------------------------------------------------------------
# G3 — deterministic derivation
# ---------------------------------------------------------------------------

def check_g3(candidate: Candidate, document: ParsedDocument, *,
             policy: str = "auto",
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

    source_text = candidate.evidence[0].source_text if candidate.evidence else candidate.raw
    convention = detect_document_convention(document.text)

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
            label_is_ambiguous=aliases.is_ambiguous_count_label(candidate.label_text),
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
            label=candidate.label_text,
            label_kg=aliases.label_declares_kg(candidate.label_text),
            label_tonnes=aliases.label_declares_tonnes(candidate.label_text),
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
    return check_g3(candidate, document, policy=policy, reference_values=reference_values)
