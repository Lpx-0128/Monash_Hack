"""Conversion between Person A's internal results and the shared contract shapes.

This is the only module in the package that imports ``backend.schemas``. It emits
contract-defined fields and JSON scalars only: no source bytes, no file paths, no
provider responses, no email body and no invented Case property.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Optional, Sequence

from .. import schemas
from .comparison import FieldComparisonResult
from .pipeline import (
    AutomatedAnalysis,
    DocumentRefResult,
    ReviewOptionRequirement,
    ReviewRequirement,
)
from .recomputation import (
    DOCUMENT_CONFIRMED,
    MANUAL_OVERRIDE,
    OverrideConfirmation,
    ValidatedDecision,
)
from .types import (
    Candidate,
    DocxParagraph,
    DocxTableCell,
    Evidence,
    ExtractionMethod,
    Locator,
    NormalizedValue,
    PdfPage,
    SheetCell,
    TextRange,
    ValueKind,
)

VERSION = "wire-1.0.0"

_LOCATOR_TYPES = {
    "text_range": TextRange,
    "pdf_page": PdfPage,
    "docx_paragraph": DocxParagraph,
    "docx_table_cell": DocxTableCell,
    "sheet_cell": SheetCell,
}


def locator_from_wire(payload: Mapping) -> Locator:
    kind = payload.get("kind")
    cls = _LOCATOR_TYPES.get(kind)
    if cls is None:
        raise ValueError(f"unsupported locator kind {kind!r}")
    fields = {k: v for k, v in payload.items() if k != "kind"}
    return cls(**fields)


def evidence_to_wire(evidence: Sequence[Evidence]) -> list[schemas.EvidenceRef]:
    return [
        schemas.EvidenceRef(
            document_id=reference.document_id,
            locator=reference.locator.to_wire(),
            source_text=reference.source_text,
        )
        for reference in evidence
    ]


def _resolved_by(candidate: Candidate) -> schemas.ResolvedBy:
    if candidate.method is ExtractionMethod.HUMAN:
        return schemas.ResolvedBy.HUMAN
    if candidate.method is ExtractionMethod.AI:
        return schemas.ResolvedBy.AI
    return schemas.ResolvedBy.DETERMINISTIC


def field_value_to_wire(candidate: Optional[Candidate], *,
                        value_origin: Optional[str] = None,
                        grounded: Optional[bool] = None,
                        override_confirmations: Sequence[OverrideConfirmation] = ()
                        ) -> Optional[schemas.FieldValue]:
    """One contract FieldValue with complete provenance, or ``None``."""
    if candidate is None or candidate.normalized is None:
        return None

    if value_origin is None:
        value_origin = (
            MANUAL_OVERRIDE if "MANUAL_OVERRIDE" in candidate.flags
            else DOCUMENT_CONFIRMED if candidate.method is ExtractionMethod.HUMAN
            else "DOCUMENT_EXTRACTED"
        )
    if grounded is None:
        grounded = value_origin != MANUAL_OVERRIDE

    evidence = evidence_to_wire(candidate.evidence)
    if candidate.unit_evidence is not None:
        unit_ref = evidence_to_wire((candidate.unit_evidence,))[0]
        if unit_ref not in evidence:
            evidence.append(unit_ref)

    return schemas.FieldValue(
        raw=candidate.raw,
        normalized=candidate.normalized.to_wire(),
        evidence=evidence,
        resolved_by=_resolved_by(candidate),
        value_origin=schemas.ValueOrigin(value_origin),
        grounded=bool(grounded),
        flags=list(candidate.flags),
        override_confirmations=[
            schemas.OverrideConfirmation(
                review_id=confirmation.review_id,
                run_id=confirmation.run_id,
                field=schemas.CanonicalField(confirmation.field),
                side=schemas.Side(confirmation.side),
                proposed_value=confirmation.proposed_value,
                confirmed=confirmation.confirmed,
            )
            for confirmation in override_confirmations
        ],
    )


def comparison_to_wire(result: FieldComparisonResult,
                       overrides: Mapping[tuple, Sequence[OverrideConfirmation]] = None
                       ) -> schemas.FieldComparison:
    """One contract FieldComparison. NOT_COMPARABLE iff a cause is present."""
    overrides = overrides or {}
    si = field_value_to_wire(
        result.si, override_confirmations=overrides.get((result.field, "SI"), ())
    )
    bl = field_value_to_wire(
        result.bl, override_confirmations=overrides.get((result.field, "BL"), ())
    )
    cause = (schemas.NotComparableCause(result.not_comparable_cause)
             if result.not_comparable_cause else None)
    return schemas.FieldComparison(
        field=schemas.CanonicalField(result.field),
        si=si, bl=bl,
        result=schemas.FieldResult(result.result),
        not_comparable_cause=cause,
        compared_by=schemas.ResolvedBy(result.compared_by),
    )


def comparisons_to_wire(results: Sequence[FieldComparisonResult],
                        overrides: Mapping[tuple, Sequence[OverrideConfirmation]] = None
                        ) -> list[schemas.FieldComparison]:
    return [comparison_to_wire(result, overrides) for result in results]


def document_refs_to_wire(documents: Sequence[DocumentRefResult]) -> list[schemas.DocumentRef]:
    return [
        schemas.DocumentRef(
            document_id=document.document_id,
            role=schemas.DocumentRole(document.role),
            filename=document.filename,
            media_type=document.media_type,
            size_bytes=document.size_bytes,
            content_hash=document.content_hash,
            demo_safe=document.demo_safe,
            parse_status=document.parse_status,
        )
        for document in documents
    ]


def assessment_to_wire(analysis: AutomatedAnalysis, assessed_at: str
                       ) -> Optional[schemas.MachineAssessment]:
    if analysis.assessment is None:
        return None
    return schemas.MachineAssessment(
        status=schemas.MachineStatus(analysis.assessment.status),
        review_reason=(schemas.ReviewReason(analysis.assessment.review_reason)
                       if analysis.assessment.review_reason else None),
        has_defect=analysis.assessment.has_defect,
        defect_fields=[schemas.CanonicalField(f) for f in analysis.assessment.defect_fields],
        assessed_at=assessed_at,
    )


def _option_to_wire(option: ReviewOptionRequirement) -> schemas.ReviewOption:
    """Discriminated option shapes: an irrelevant null key is never serialized."""
    payload = {"option_id": option.option_id, "kind": option.kind, "label": option.label}
    if option.kind == "DOCUMENT":
        payload["document_id"] = option.document_id
    elif option.kind == "VALUE":
        payload["value"] = field_value_to_wire(option.value)
    return schemas.ReviewOption(**payload)


def review_to_wire(requirement: ReviewRequirement, *, review_id: str, case_id: str,
                   run_id: str, created_at: str,
                   documents: Sequence[DocumentRefResult]) -> schemas.Review:
    """Build the contract Review from Person A's requirement."""
    by_id = {document.document_id: document for document in documents}
    sources = [
        schemas.SourceDocument(
            document_id=document_id,
            filename=by_id[document_id].filename,
            media_type=by_id[document_id].media_type,
        )
        for document_id in requirement.source_document_ids
        if document_id in by_id
    ]
    return schemas.Review(
        review_id=review_id,
        case_id=case_id,
        run_id=run_id,
        status=schemas.ReviewStatus.OPEN,
        scope=schemas.ReviewScope(requirement.scope),
        ui_mode=schemas.ReviewUiMode(requirement.ui_mode),
        reason=schemas.ReviewReason(requirement.reason),
        field=schemas.CanonicalField(requirement.field) if requirement.field else None,
        side=schemas.Side(requirement.side) if requirement.side else None,
        target_role=schemas.Side(requirement.target_role) if requirement.target_role else None,
        question=requirement.question,
        context_summary=requirement.context_summary,
        options=[_option_to_wire(option) for option in requirement.options] or None,
        allowed_actions=[schemas.DecisionAction(a) for a in requirement.allowed_actions],
        source_documents=sources,
        created_at=created_at,
        notified_at=None,
        closed_at=None,
        close_reason=None,
    )


# ---------------------------------------------------------------------------
# Accepted-decision records
# ---------------------------------------------------------------------------

def _normalized_to_json(value: NormalizedValue) -> dict:
    return {
        "kind": value.kind.value,
        "text": value.text,
        "number": str(value.number) if value.number is not None else None,
    }


def _normalized_from_json(payload: Mapping) -> NormalizedValue:
    kind = ValueKind(payload["kind"])
    number = Decimal(payload["number"]) if payload.get("number") is not None else None
    return NormalizedValue(kind=kind, text=payload.get("text"), number=number)


def _candidate_to_json(candidate: Candidate) -> dict:
    return {
        "field": candidate.field,
        "side": candidate.side,
        "document_id": candidate.document_id,
        "raw": candidate.raw,
        "label_text": candidate.label_text,
        "evidence": [
            {"document_id": e.document_id, "locator": e.locator.to_wire(),
             "source_text": e.source_text}
            for e in candidate.evidence
        ],
        "derivation": candidate.derivation.value,
        "method": candidate.method.value,
        "normalized": _normalized_to_json(candidate.normalized) if candidate.normalized else None,
        "reference_field": candidate.reference_field,
        "flags": list(candidate.flags),
        # The block binding must survive: an unbound candidate cannot be
        # re-grounded, so losing it here would break G1/G2 on resumption.
        "block_id": candidate.block_id,
        "reference_block_id": candidate.reference_block_id,
        "components": list(candidate.components),
        "issues": list(candidate.issues),
        "unit_evidence": (
            {"document_id": candidate.unit_evidence.document_id,
             "locator": candidate.unit_evidence.locator.to_wire(),
             "source_text": candidate.unit_evidence.source_text}
            if candidate.unit_evidence else None
        ),
    }


def _candidate_from_json(payload: Mapping) -> Candidate:
    from .types import Derivation

    return Candidate(
        field=payload["field"], side=payload["side"], document_id=payload["document_id"],
        raw=payload["raw"], label_text=payload.get("label_text"),
        evidence=tuple(
            Evidence(e["document_id"], locator_from_wire(e["locator"]), e["source_text"])
            for e in payload.get("evidence", [])
        ),
        derivation=Derivation(payload["derivation"]),
        method=ExtractionMethod(payload["method"]),
        normalized=_normalized_from_json(payload["normalized"]) if payload.get("normalized") else None,
        reference_field=payload.get("reference_field"),
        flags=tuple(payload.get("flags", [])),
        block_id=payload.get("block_id"),
        reference_block_id=payload.get("reference_block_id"),
        components=tuple(payload.get("components", [])),
        issues=tuple(payload.get("issues", [])),
        unit_evidence=(
            Evidence(payload["unit_evidence"]["document_id"],
                     locator_from_wire(payload["unit_evidence"]["locator"]),
                     payload["unit_evidence"]["source_text"])
            if payload.get("unit_evidence") else None
        ),
    )


def decision_to_json(decision: ValidatedDecision) -> dict:
    """The immutable accepted-decision payload Person B persists with the job."""
    confirmation = decision.override_confirmation
    return {
        "decision_id": decision.decision_id,
        "review_id": decision.review_id,
        "run_id": decision.run_id,
        "action": decision.action,
        "actor_id": decision.actor_id,
        "channel": decision.channel,
        "target_field": decision.target_field,
        "target_side": decision.target_side,
        "target_role": decision.target_role,
        "selected_document_id": decision.selected_document_id,
        "canonical": _candidate_to_json(decision.canonical) if decision.canonical else None,
        "value_origin": decision.value_origin,
        "grounded": decision.grounded,
        "escape": decision.escape,
        "option_id": decision.option_id,
        "user_message": decision.user_message,
        "override_confirmation": (
            {
                "review_id": confirmation.review_id, "run_id": confirmation.run_id,
                "field": confirmation.field, "side": confirmation.side,
                "proposed_value": confirmation.proposed_value,
                "confirmed": confirmation.confirmed,
            }
            if confirmation else None
        ),
        "input_version": decision.input_version,
        "config_version": decision.config_version,
    }


def decision_from_json(payload: Mapping) -> ValidatedDecision:
    confirmation = payload.get("override_confirmation")
    return ValidatedDecision(
        decision_id=payload["decision_id"], review_id=payload["review_id"],
        run_id=payload["run_id"], action=payload["action"], actor_id=payload["actor_id"],
        channel=payload["channel"], target_field=payload.get("target_field"),
        target_side=payload.get("target_side"), target_role=payload.get("target_role"),
        selected_document_id=payload.get("selected_document_id"),
        canonical=_candidate_from_json(payload["canonical"]) if payload.get("canonical") else None,
        value_origin=payload.get("value_origin"), grounded=bool(payload.get("grounded")),
        escape=bool(payload.get("escape")), option_id=payload.get("option_id"),
        user_message=payload.get("user_message"),
        override_confirmation=(
            OverrideConfirmation(
                review_id=confirmation["review_id"], run_id=confirmation["run_id"],
                field=confirmation["field"], side=confirmation["side"],
                proposed_value=confirmation["proposed_value"],
                confirmed=confirmation["confirmed"],
            )
            if confirmation else None
        ),
        input_version=payload.get("input_version", ""),
        config_version=payload.get("config_version", ""),
    )


def review_requirement_to_json(requirement: ReviewRequirement) -> dict:
    """Persisted so a resumption can re-validate against the same review."""
    return {
        "scope": requirement.scope, "ui_mode": requirement.ui_mode,
        "reason": requirement.reason, "question": requirement.question,
        "context_summary": requirement.context_summary,
        "allowed_actions": list(requirement.allowed_actions),
        "field": requirement.field, "side": requirement.side,
        "target_role": requirement.target_role,
        "options": [
            {"option_id": o.option_id, "kind": o.kind, "label": o.label,
             "document_id": o.document_id,
             "value": _candidate_to_json(o.value) if o.value else None}
            for o in requirement.options
        ],
        "source_document_ids": list(requirement.source_document_ids),
        "blocks_externally": requirement.blocks_externally,
    }


def review_requirement_from_json(payload: Mapping) -> ReviewRequirement:
    return ReviewRequirement(
        scope=payload["scope"], ui_mode=payload["ui_mode"], reason=payload["reason"],
        question=payload["question"], context_summary=payload["context_summary"],
        allowed_actions=tuple(payload["allowed_actions"]),
        field=payload.get("field"), side=payload.get("side"),
        target_role=payload.get("target_role"),
        options=tuple(
            ReviewOptionRequirement(
                option_id=o["option_id"], kind=o["kind"], label=o["label"],
                document_id=o.get("document_id"),
                value=_candidate_from_json(o["value"]) if o.get("value") else None,
            )
            for o in payload.get("options", [])
        ),
        source_document_ids=tuple(payload.get("source_document_ids", [])),
        blocks_externally=bool(payload.get("blocks_externally")),
    )


def requirement_from_review(review: schemas.Review) -> ReviewRequirement:
    """Rebuild Person A's requirement from the Review Person B persisted.

    The persisted Review is the authority, so a decision arriving after a process
    restart is validated against exactly the review the person was shown.
    """
    options = []
    for option in review.options or []:
        value = None
        if option.kind == "VALUE" and option.value is not None:
            evidence = tuple(
                Evidence(reference.document_id, locator_from_wire(reference.locator),
                         reference.source_text)
                for reference in option.value.evidence
            )
            value = Candidate(
                field=review.field.value if review.field else "",
                side=review.side.value if review.side else "",
                document_id=evidence[0].document_id if evidence else "",
                raw=option.value.raw or "",
                label_text=None,
                evidence=evidence,
                normalized=_normalized_from_wire(review.field, option.value.normalized),
            )
        options.append(ReviewOptionRequirement(
            option_id=option.option_id, kind=option.kind, label=option.label,
            document_id=option.document_id, value=value,
        ))

    return ReviewRequirement(
        scope=review.scope.value,
        ui_mode=review.ui_mode.value,
        reason=review.reason.value,
        question=review.question,
        context_summary=review.context_summary,
        allowed_actions=tuple(action.value for action in review.allowed_actions),
        field=review.field.value if review.field else None,
        side=review.side.value if review.side else None,
        target_role=review.target_role.value if review.target_role else None,
        options=tuple(options),
        source_document_ids=tuple(d.document_id for d in review.source_documents),
        blocks_externally=review.ui_mode is schemas.ReviewUiMode.ACKNOWLEDGE,
    )


def _normalized_from_wire(field, value) -> Optional[NormalizedValue]:
    """Rebuild the canonical value a persisted option carries."""
    if value is None:
        return None
    name = field.value if hasattr(field, "value") else field
    if name == "container_count":
        return NormalizedValue.of_integer(Decimal(str(value)))
    if name == "gross_weight_kg":
        return NormalizedValue.of_decimal(Decimal(str(value)))
    return NormalizedValue.of_text(str(value))


# ---------------------------------------------------------------------------
# Machine-state snapshot
# ---------------------------------------------------------------------------
#
# The automated pass can involve a model, whose answers are not reproducible by
# rerunning it. Resumption therefore restores what the run actually decided
# rather than recomputing it: the classification, the role assignment and every
# field outcome with its block binding, evidence and provenance.

def field_outcome_to_json(outcome) -> dict:
    return {
        "field": outcome.field,
        "side": outcome.side,
        "value": _candidate_to_json(outcome.value) if outcome.value else None,
        "cause": outcome.cause.value if outcome.cause else None,
        "detail": outcome.detail,
        "alternatives": [_candidate_to_json(c) for c in outcome.alternatives],
    }


def field_outcome_from_json(payload: Mapping):
    from .types import FieldOutcome, UncertaintyCause

    return FieldOutcome(
        field=payload["field"],
        side=payload["side"],
        value=_candidate_from_json(payload["value"]) if payload.get("value") else None,
        cause=UncertaintyCause(payload["cause"]) if payload.get("cause") else None,
        detail=payload.get("detail", ""),
        alternatives=tuple(_candidate_from_json(c) for c in payload.get("alternatives", [])),
    )


def machine_state_to_json(analysis) -> dict:
    """Everything resumption needs that rerunning the rules would not reproduce."""
    roles = analysis.roles
    return {
        "category": analysis.category,
        "classified_by": analysis.classified_by,
        "classification_reason": analysis.classification_reason,
        "roles": {
            "si": roles.si if roles else None,
            "bl": roles.bl if roles else None,
            "issues": list(roles.issues) if roles else [],
            "si_alternatives": list(roles.si_alternatives) if roles else [],
            "bl_alternatives": list(roles.bl_alternatives) if roles else [],
        },
        "si_fields": {name: field_outcome_to_json(o) for name, o in analysis.si_fields.items()},
        "bl_fields": {name: field_outcome_to_json(o) for name, o in analysis.bl_fields.items()},
        "documents": [
            {"document_id": d.document_id, "role": d.role, "filename": d.filename,
             "media_type": d.media_type, "size_bytes": d.size_bytes,
             "content_hash": d.content_hash, "demo_safe": d.demo_safe,
             "parse_status": d.parse_status}
            for d in analysis.documents
        ],
        "ai_calls": analysis.ai_calls,
        "ai_assisted_fields": analysis.ai_assisted_fields,
    }


def machine_state_from_json(payload: Mapping) -> dict:
    """Rehydrate the stored machine interpretation."""
    from .pipeline import DocumentRefResult
    from .roles import RoleResolution

    roles_payload = payload.get("roles") or {}
    roles = RoleResolution(
        si=roles_payload.get("si"),
        bl=roles_payload.get("bl"),
        assessments=(),
        si_alternatives=tuple(roles_payload.get("si_alternatives", [])),
        bl_alternatives=tuple(roles_payload.get("bl_alternatives", [])),
        issues=tuple(roles_payload.get("issues", [])),
    )
    return {
        "category": payload.get("category"),
        "classified_by": payload.get("classified_by"),
        "classification_reason": payload.get("classification_reason", ""),
        "roles": roles,
        "si_fields": {k: field_outcome_from_json(v)
                      for k, v in (payload.get("si_fields") or {}).items()},
        "bl_fields": {k: field_outcome_from_json(v)
                      for k, v in (payload.get("bl_fields") or {}).items()},
        "documents": tuple(
            DocumentRefResult(**d) for d in payload.get("documents", [])
        ),
        "ai_calls": payload.get("ai_calls", 0),
        "ai_assisted_fields": payload.get("ai_assisted_fields", 0),
    }
