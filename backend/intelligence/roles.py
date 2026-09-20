"""Content-backed SI / BL / OTHER / UNKNOWN role assignment (handoff §12).

A filename is never role proof: ``email_501_BL.txt`` in the corpus is a
commercial invoice. Filename and email-body hints only rank candidates; the
document heading and body decide.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field
from typing import Optional, Sequence

from .parsers.base import heading_text
from .policies import aliases
from .types import ParsedDocument, ParseStatus

VERSION = "roles-1.0.0"

SI = "SI"
BL = "BL"
OTHER = "OTHER"
UNKNOWN = "UNKNOWN"

_SI_HEADING = re.compile(
    r"\b(?:shipping\s+instructions?|shipment\s+instructions?|b/?l\s+instructions?|"
    r"bl\s+instruction|bill\s+of\s+lading\s+instructions?|booking\s+instructions?)\b",
    re.IGNORECASE,
)
# "BILL OF LADING INSTRUCTION" is a shipping instruction, not a bill of lading,
# so the BL heading stops before the word "instruction".
_BL_HEADING = re.compile(
    r"\b(?:(?:draft\s+)?bill\s+of\s+lading(?!\s+instruction)|b/?l\s+draft|"
    r"ocean\s+bill\s+of\s+lading(?!\s+instruction)|"
    r"house\s+bill\s+of\s+lading(?!\s+instruction)|sea\s+waybill)\b",
    re.IGNORECASE,
)
_OTHER_HEADING = re.compile(
    r"\b(?:commercial\s+invoice|proforma\s+invoice|packing\s+list|"
    r"certificate\s+of\s+origin|certificate\s+of\s+analysis|insurance\s+certificate|"
    r"debit\s+note|credit\s+note|delivery\s+order)\b",
    re.IGNORECASE,
)

# "This is NOT a shipping instruction" must not count as a positive signal.
_NEGATED = re.compile(
    r"\b(?:not|isn'?t|is\s+not|never)\b[^.\n]{0,30}$",
    re.IGNORECASE,
)

# Body markers that support a role beyond the heading.
_BL_BODY = re.compile(
    r"\b(?:b/?l\s*(?:no|number)|bill\s+of\s+lading\s+no|export\s+carrier|"
    r"on\s+board\s+date|freight\s+(?:prepaid|collect))\b",
    re.IGNORECASE,
)
_SI_BODY = re.compile(
    r"\b(?:booking\s+(?:ref|reference|no)|oc\s+no|shipping\s+mark|"
    r"kinds\s+of\s+packages)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RoleAssessment:
    """One document's role, with the evidence and confidence behind it."""

    document_id: str
    role: str
    score: float
    reason: str
    heading: str = ""
    field_labels: int = 0
    readable: bool = True


@dataclass(frozen=True)
class RoleResolution:
    """Assignments, alternatives and the issues that need a person."""

    si: Optional[str] = None
    bl: Optional[str] = None
    assessments: tuple[RoleAssessment, ...] = ()
    si_alternatives: tuple[str, ...] = ()
    bl_alternatives: tuple[str, ...] = ()
    issues: tuple[str, ...] = dc_field(default_factory=tuple)

    def role_of(self, document_id: str) -> str:
        if document_id == self.si:
            return SI
        if document_id == self.bl:
            return BL
        for assessment in self.assessments:
            if assessment.document_id == document_id:
                return assessment.role if assessment.role != SI and assessment.role != BL else OTHER
        return UNKNOWN


def _negated_at(text: str, match: re.Match) -> bool:
    window_start = max(0, match.start() - 40)
    return _NEGATED.search(text[window_start:match.start()]) is not None


def _count_field_labels(document: ParsedDocument) -> int:
    fields = {aliases.match_field(block.label) for block in document.blocks}
    fields.discard(None)
    return len(fields)


def assess_document(document: ParsedDocument) -> RoleAssessment:
    """Score one parsed document against each role using positive content signals."""
    if document.status is not ParseStatus.OK:
        return RoleAssessment(
            document_id=document.document_id, role=UNKNOWN, score=0.0,
            reason=f"document is {document.status.value.lower()}", readable=False,
        )

    heading = heading_text(document.text)
    body = document.text
    field_labels = _count_field_labels(document)

    def hits(pattern: re.Pattern, text: str) -> int:
        return sum(1 for m in pattern.finditer(text) if not _negated_at(text, m))

    si_score = 3.0 * hits(_SI_HEADING, heading) + 1.0 * hits(_SI_HEADING, body) + 0.5 * hits(_SI_BODY, body)
    bl_score = 3.0 * hits(_BL_HEADING, heading) + 1.0 * hits(_BL_HEADING, body) + 0.5 * hits(_BL_BODY, body)
    other_score = 4.0 * hits(_OTHER_HEADING, heading) + 1.0 * hits(_OTHER_HEADING, body)

    ranked = sorted(
        ((other_score, OTHER), (bl_score, BL), (si_score, SI)),
        key=lambda pair: pair[0], reverse=True,
    )
    top_score, top_role = ranked[0]
    runner_score = ranked[1][0]

    if top_score <= 0:
        return RoleAssessment(
            document_id=document.document_id, role=UNKNOWN, score=0.0,
            reason="no document type could be established from the content",
            heading=heading, field_labels=field_labels,
        )
    if top_score == runner_score:
        return RoleAssessment(
            document_id=document.document_id, role=UNKNOWN, score=top_score,
            reason="content supports more than one document type equally",
            heading=heading, field_labels=field_labels,
        )

    return RoleAssessment(
        document_id=document.document_id, role=top_role, score=top_score,
        reason=f"content signals support {top_role}", heading=heading,
        field_labels=field_labels,
    )


def resolve_roles(documents: Sequence[ParsedDocument],
                  filename_hints: Optional[dict] = None) -> RoleResolution:
    """Assign at most one SI and one BL from content, retaining alternatives.

    One document may not occupy both roles, and the first two attachments are
    never selected merely because of their position.
    """
    hints = filename_hints or {}
    assessments = tuple(assess_document(document) for document in documents)

    def candidates(role: str) -> list[RoleAssessment]:
        matching = [a for a in assessments if a.role == role]
        # Tie-break deterministically: stronger content, then more canonical field
        # labels, then a filename hint, then document id.
        return sorted(
            matching,
            key=lambda a: (-a.score, -a.field_labels, hints.get(a.document_id) != role, a.document_id),
        )

    issues: list[str] = []
    si_candidates = candidates(SI)
    bl_candidates = candidates(BL)

    def pick(cands: list[RoleAssessment]) -> Optional[str]:
        """The single strongest candidate, or None when the top two tie.

        A tie is a genuine document question: choosing the first attachment or
        the newest-looking filename would be an arbitrary selection.
        """
        if not cands:
            return None
        if len(cands) > 1 and cands[0].score == cands[1].score:
            return None
        return cands[0].document_id

    si_id = pick(si_candidates)
    bl_id = pick(bl_candidates)

    if si_id is not None and si_id == bl_id:  # defensive: a role assessment is singular
        bl_id = None

    def plausible_alternatives(cands: list[RoleAssessment], chosen: Optional[str],
                               taken: Optional[str]) -> tuple[str, ...]:
        return tuple(
            a.document_id for a in cands
            if a.document_id != chosen and a.document_id != taken
        )

    si_alternatives = plausible_alternatives(si_candidates, si_id, bl_id)
    bl_alternatives = plausible_alternatives(bl_candidates, bl_id, si_id)

    # Issue names are prefixed with the role they concern, so resolving that role
    # clears every issue about it.
    if len(si_candidates) > 1 and si_candidates[0].score == si_candidates[1].score:
        issues.append("SI_AMBIGUOUS_CANDIDATES")
    if len(bl_candidates) > 1 and bl_candidates[0].score == bl_candidates[1].score:
        issues.append("BL_AMBIGUOUS_CANDIDATES")

    unreadable = [a for a in assessments if not a.readable]

    def classify_gap(role: str, taken: Optional[str]) -> tuple[str, tuple[str, ...]]:
        """Why a role is unfilled: unresolved candidates, wrong type, unreadable, or absent."""
        tied = [a for a in candidates(role) if a.document_id != taken]
        if len(tied) > 1:
            return f"{role}_ROLE_UNRESOLVED", tuple(a.document_id for a in tied)
        unknowns = [a for a in assessments if a.role == UNKNOWN and a.readable
                    and a.document_id != taken]
        if unknowns:
            return f"{role}_ROLE_UNRESOLVED", tuple(a.document_id for a in unknowns)
        if unreadable:
            # A document was supplied; it just could not be read. That is an
            # unreadable source, not a missing attachment.
            return f"{role}_UNREADABLE", ()
        if any(a.role == OTHER for a in assessments):
            return f"{role}_WRONG_DOC_TYPE", ()
        return f"{role}_MISSING", ()

    if si_id is None:
        issue, alternatives = classify_gap(SI, bl_id)
        issues.append(issue)
        if alternatives:
            si_alternatives = alternatives
    if bl_id is None:
        issue, alternatives = classify_gap(BL, si_id)
        issues.append(issue)
        if alternatives:
            bl_alternatives = alternatives

    if unreadable:
        issues.append("UNREADABLE_DOCUMENT")

    return RoleResolution(
        si=si_id, bl=bl_id, assessments=assessments,
        si_alternatives=si_alternatives, bl_alternatives=bl_alternatives,
        issues=tuple(dict.fromkeys(issues)),
    )


def filename_hint(filename: str) -> Optional[str]:
    """A weak ranking hint only. It can never overrule document content."""
    upper = (filename or "").upper()
    if "_SI." in upper or upper.endswith("_SI"):
        return SI
    if "_BL." in upper or upper.endswith("_BL"):
        return BL
    return None
