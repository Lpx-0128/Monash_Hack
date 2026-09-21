"""Deterministic comparison and assessment roll-up (handoff §§15.7, 16)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from .policies import ports as port_policy
from .types import (
    CANONICAL_FIELDS,
    Candidate,
    FieldOutcome,
    NormalizedValue,
    PORT_FIELDS,
    UncertaintyCause,
)

VERSION = "comparison-1.0.0"

MATCH = "MATCH"
MISMATCH = "MISMATCH"
NOT_COMPARABLE = "NOT_COMPARABLE"

AUTOMATED = "AUTOMATED"
OPERATIONAL = "OPERATIONAL"

# Private uncertainty cause -> contract NotComparableCause.
_CAUSE_MAP = {
    UncertaintyCause.MISSING_VALUE: "MISSING_VALUE",
    UncertaintyCause.MISSING_UNIT: "UNREADABLE",
    UncertaintyCause.AMBIGUOUS_SEPARATOR: "AMBIGUOUS",
    UncertaintyCause.COMPETING_CANDIDATES: "AMBIGUOUS",
    UncertaintyCause.UNGROUNDED: "UNGROUNDED",
    UncertaintyCause.INVALID_VALUE: "INVALID_VALUE",
    UncertaintyCause.UNREADABLE_DOCUMENT: "UNREADABLE",
    UncertaintyCause.DOCUMENT_LEVEL: "DOCUMENT_LEVEL",
    UncertaintyCause.SEMANTIC_UNCERTAIN: "SEMANTIC_UNCERTAIN",
}

# Contract review reasons, most severe first.
REASON_PRIORITY = ("missing_attachment", "wrong_doc_type", "unreadable", "missing_value")

# Which review reason a field-level cause maps to.
_REASON_FOR_CAUSE = {
    UncertaintyCause.MISSING_VALUE: "missing_value",
    UncertaintyCause.MISSING_UNIT: "unreadable",
    UncertaintyCause.AMBIGUOUS_SEPARATOR: "unreadable",
    UncertaintyCause.COMPETING_CANDIDATES: "unreadable",
    UncertaintyCause.UNGROUNDED: "unreadable",
    UncertaintyCause.INVALID_VALUE: "unreadable",
    UncertaintyCause.UNREADABLE_DOCUMENT: "unreadable",
    UncertaintyCause.SEMANTIC_UNCERTAIN: "unreadable",
    UncertaintyCause.DOCUMENT_LEVEL: "missing_attachment",
}


@dataclass(frozen=True)
class FieldComparisonResult:
    """One field's comparison, with the private cause retained alongside it."""

    field: str
    si: Optional[Candidate]
    bl: Optional[Candidate]
    result: str
    not_comparable_cause: Optional[str] = None
    compared_by: str = "DETERMINISTIC"
    private_cause: Optional[UncertaintyCause] = None
    detail: str = ""


def values_equal(field: str, left: NormalizedValue, right: NormalizedValue) -> bool:
    """Exact equality under the field's policy. No tolerance, no fuzzy matching."""
    if field in PORT_FIELDS:
        if left.text is None or right.text is None:
            return False
        return port_policy.equal(left.text, right.text)
    return left.equals(right)


def compare_field(field: str, si: FieldOutcome, bl: FieldOutcome, *,
                  mode: str = AUTOMATED) -> FieldComparisonResult:
    """Compare one field, or explain precisely why it is not comparable.

    ``compared_by`` stays DETERMINISTIC for exact text or numeric equality even
    when a side's value came from a person: the FieldValue records that HUMAN
    provenance, but the arithmetic is still deterministic.
    """
    si_value = si.value if si.resolved else None
    bl_value = bl.value if bl.resolved else None

    if si_value is None or bl_value is None:
        cause = si.cause if si_value is None else bl.cause
        detail = si.detail if si_value is None else bl.detail
        if cause is None:
            cause = UncertaintyCause.MISSING_VALUE
        return FieldComparisonResult(
            field=field, si=si_value, bl=bl_value, result=NOT_COMPARABLE,
            not_comparable_cause=_CAUSE_MAP[cause], private_cause=cause, detail=detail,
        )

    equal = values_equal(field, si_value.normalized, bl_value.normalized)
    return FieldComparisonResult(
        field=field, si=si_value, bl=bl_value,
        result=MATCH if equal else MISMATCH,
        not_comparable_cause=None,
        compared_by="DETERMINISTIC",
    )


def compare_all(si_fields: Mapping[str, FieldOutcome], bl_fields: Mapping[str, FieldOutcome],
                *, mode: str = AUTOMATED) -> tuple[FieldComparisonResult, ...]:
    """All seven canonical fields, in the required order."""
    return tuple(
        compare_field(field, si_fields[field], bl_fields[field], mode=mode)
        for field in CANONICAL_FIELDS
    )


@dataclass(frozen=True)
class Assessment:
    """A frozen roll-up: machine status, its reason and the defect fields."""

    status: str                       # OK | MISMATCH | NEEDS_REVIEW
    review_reason: Optional[str]
    has_defect: bool
    defect_fields: tuple[str, ...]
    detail: str = ""


def _document_reason(document_issues: Sequence[str]) -> Optional[str]:
    """Map role-resolution issues to the most severe contract review reason."""
    reasons: list[str] = []
    for issue in document_issues:
        if issue.endswith("_MISSING") or issue == "SOURCE_MISSING":
            reasons.append("missing_attachment")
        elif issue.endswith("_WRONG_DOC_TYPE"):
            reasons.append("wrong_doc_type")
        elif issue.endswith("_UNREADABLE") or issue == "UNREADABLE_DOCUMENT":
            reasons.append("unreadable")
        elif issue.endswith("_ROLE_UNRESOLVED") or issue.endswith("_AMBIGUOUS_CANDIDATES"):
            reasons.append("wrong_doc_type")
    if not reasons:
        return None
    return min(reasons, key=REASON_PRIORITY.index)


def roll_up(category: str, comparisons: Sequence[FieldComparisonResult],
            document_issues: Sequence[str] = ()) -> Assessment:
    """Apply the roll-up precedence exactly (handoff §16).

    1. non-BL category   -> OK, no fields
    2. document problem  -> NEEDS_REVIEW
    3. any NOT_COMPARABLE-> NEEDS_REVIEW
    4. any MISMATCH      -> MISMATCH
    5. all seven MATCH   -> OK

    A known mismatch stays visible in the working field table even when
    NEEDS_REVIEW takes precedence; the exported defect list is then empty.
    """
    if category != "BL_COMPARISON":
        return Assessment(status="OK", review_reason=None, has_defect=False, defect_fields=())

    document_reason = _document_reason(document_issues)
    if document_reason is not None:
        return Assessment(status="NEEDS_REVIEW", review_reason=document_reason,
                          has_defect=False, defect_fields=(),
                          detail=f"document-level issues: {', '.join(document_issues)}")

    not_comparable = [c for c in comparisons if c.result == NOT_COMPARABLE]
    if not_comparable:
        reasons = [
            _REASON_FOR_CAUSE.get(c.private_cause or UncertaintyCause.MISSING_VALUE, "unreadable")
            for c in not_comparable
        ]
        reason = min(reasons, key=REASON_PRIORITY.index)
        return Assessment(
            status="NEEDS_REVIEW", review_reason=reason, has_defect=False, defect_fields=(),
            detail="; ".join(f"{c.field}: {c.not_comparable_cause}" for c in not_comparable),
        )

    mismatched = tuple(c.field for c in comparisons if c.result == MISMATCH)
    if mismatched:
        return Assessment(status="MISMATCH", review_reason=None, has_defect=True,
                          defect_fields=mismatched)

    return Assessment(status="OK", review_reason=None, has_defect=False, defect_fields=())
