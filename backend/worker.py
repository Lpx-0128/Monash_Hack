"""Worker entry points, driven by real document analysis.

``process_case`` runs Person A's ``analyze_case`` against the run's immutable
input and freezes the result. ``apply_decision`` applies the accepted decision
record bound to its job — there is no default value, no reconstruction from
history, and the frozen machine assessment is never rewritten.
"""

import itertools
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text as sa_text

from . import crud, database, models, schemas
from .intelligence import ai as ai_module
from .intelligence import wire
from .intelligence import pipeline as pipeline_module
from .intelligence.pipeline import AnalysisContext, IntelligenceServices, analyze_case
from .intelligence.recomputation import (
    WorkingAnalysis,
    apply_validated_decision,
    working_state_from_analysis,
)
from .intelligence.types import (
    PermanentProcessingError,
    RetryableProcessingError,
    SourceDataIssue,
)

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _stale_run(db, case_id: str, expected_run_id: str) -> bool:
    """True when the case's current run no longer matches ``expected_run_id``."""
    db_case = crud.get_case(db, case_id)
    if db_case is None:
        return True
    return crud.map_db_to_schema(db_case).run.run_id != expected_run_id


def _event(case: schemas.Case, event_type: str, summary: str,
           actor_kind: str = "SYSTEM", actor_id: Optional[str] = None,
           details=None, at: Optional[str] = None) -> None:
    case.history.append(schemas.HistoryEvent(
        event_id=f"evt_{uuid.uuid4().hex[:8]}",
        run_id=case.run.run_id,
        at=at or _now(),
        type=event_type,
        actor=schemas.Actor(kind=actor_kind, id=actor_id),
        summary=summary,
        details=details,
    ))


def _build_context(case: schemas.Case) -> AnalysisContext:
    counter = itertools.count(1)
    return AnalysisContext(
        case_id=case.case_id,
        run_id=case.run.run_id,
        run_kind=case.run.kind.value,
        config=crud.intelligence_config(),
        now=_now,
        next_id=lambda prefix: f"{prefix}_{uuid.uuid4().hex[:8]}_{next(counter)}",
    )


def _build_services(snapshot=None) -> IntelligenceServices:
    """Services for one run.

    When the snapshot's registry has no provider consent, no provider client is
    constructed at all. The pipeline enforces the same rule again before sending
    anything, so neither layer alone is the only thing standing between
    participant correspondence and an external service.
    """
    config = crud.intelligence_config()
    consent_required = (
        snapshot is not None
        and snapshot.registry_kind in pipeline_module.CONSENT_REQUIRED_REGISTRIES
    )
    if consent_required and not config.ai.allow_participant_content:
        model = ai_module.DisabledModelClient()
    else:
        model = ai_module.build_model_client(config.ai)
    return IntelligenceServices(
        registries=crud.intelligence_registries(),
        model=model,
        budget=ai_module.CallBudget(limit=config.ai.max_calls_per_run),
    )


class RunIdentityChanged(PermanentProcessingError):
    """The run's inputs or configuration are no longer what it was computed from."""


def _source_manifest(snapshot) -> dict:
    return {ref.document_id: (ref.content_hash or "") for ref in snapshot.sources}


def save_run_snapshot(case: schemas.Case, snapshot, analysis) -> dict:
    """The row recording what this run was computed from, and what it decided."""
    return {
        "run_id": case.run.run_id,
        "case_id": case.case_id,
        "input_version": analysis.input_version,
        "config_version": analysis.config_version,
        "source_manifest": json.dumps(_source_manifest(snapshot)),
        "classification": json.dumps({
            "category": analysis.category,
            "classified_by": analysis.classified_by,
            "reason": analysis.classification_reason,
        }),
        "machine_state": json.dumps(wire.machine_state_to_json(analysis)),
        "config_manifest": json.dumps(crud.intelligence_config().manifest()),
        "created_at": _now(),
    }


def load_run_snapshot(db, run_id: str) -> Optional[models.RunSnapshotModel]:
    return (
        db.query(models.RunSnapshotModel)
        .filter_by(run_id=run_id)
        .first()
    )


class RunStateUnavailable(PermanentProcessingError):
    """The run's machine state was never recorded, so it cannot be resumed."""


def load_working_state(db, case: schemas.Case, expected_run_id: str, *,
                       up_to_decision_id: Optional[str] = None):
    """The one authoritative working state, shared by validation and application."""
    stored = load_run_snapshot(db, expected_run_id)

    if stored is None:
        raise RunStateUnavailable(
            f"run {expected_run_id} of {case.case_id} has no recorded machine state. "
            "It predates machine-state persistence, so its accepted interpretation cannot "
            "be reconstructed; reprocess the case to create a fresh run."
        )

    try:
        snapshot = crud.load_input_snapshot(case.email.email_id, case.run.kind)
    except Exception:
        snapshot = None

    if snapshot and stored.input_version != snapshot.input_version:
        raise RunIdentityChanged(
            f"the sources for {case.case_id} changed since run {expected_run_id} was "
            f"computed ({stored.input_version} -> {snapshot.input_version}); "
            "start a new run instead of applying a decision to changed input"
        )
    current_config = crud.intelligence_config().config_identity()
    if stored.config_version != current_config:
        raise RunIdentityChanged(
            f"the configuration changed since run {expected_run_id} was computed "
            f"({stored.config_version} -> {current_config}); "
            "start a new run instead of reinterpreting under a new policy"
        )
    if not stored.machine_state:
        raise RunStateUnavailable(
            f"run {expected_run_id} recorded no machine state; it cannot be resumed"
        )

    context = _build_context(case)
    if snapshot:
        services = _build_services(snapshot)
        services.model = ai_module.DisabledModelClient()
        parsed, _diagnostics = pipeline_module.parse_snapshot(snapshot, context, services)
        registry = crud.intelligence_registries().get(snapshot.registry_kind)
    else:
        parsed = {}
        registry = None

    machine_state_dict = json.loads(stored.machine_state) if isinstance(stored.machine_state, str) else stored.machine_state
    restored = wire.machine_state_from_json(machine_state_dict)

    state = WorkingAnalysis(
        snapshot=snapshot or ingestion_module.InputSnapshot(case.case_id, case.email.email_id, stored.input_version, (), "demo"),
        parsed=parsed,
        si_fields=dict(restored["si_fields"]),
        bl_fields=dict(restored["bl_fields"]),
        roles=restored["roles"],
        category=restored["category"] or "GENERAL",
        machine_assessment=_assessment_from_case(case),
        machine_comparisons=(),
        document_issues=tuple(restored["roles"].issues),
        fallback_convention=registry.numeric_convention() if registry else "",
    )

    applied = _applied_decisions(db, case.case_id, expected_run_id)
    for record in applied:
        if up_to_decision_id is not None and record.decision_id == up_to_decision_id:
            break
        decision = wire.decision_from_json(record.payload)
        state = apply_validated_decision(decision, state, context).state

    return state, context, snapshot, restored, applied


def _assessment_from_case(case: schemas.Case):
    """The frozen machine assessment, as the working state carries it."""
    from .intelligence.comparison import Assessment

    assessment = case.machine_assessment
    if assessment is None:
        return Assessment(status="NEEDS_REVIEW", review_reason=None,
                          has_defect=False, defect_fields=())
    return Assessment(
        status=assessment.status.value,
        review_reason=assessment.review_reason.value if assessment.review_reason else None,
        has_defect=assessment.has_defect,
        defect_fields=tuple(f.value for f in assessment.defect_fields),
    )


def _run_analysis(case: schemas.Case):
    """Ingest and analyze outside any database write transaction."""
    snapshot = crud.load_input_snapshot(case.email.email_id, case.run.kind)
    context = _build_context(case)
    services = _build_services(snapshot)
    analysis = analyze_case(snapshot, context, services)
    return snapshot, context, services, analysis


def _commit_case(db, db_case, case: schemas.Case, expected_run_id: str, *,
                 mark_decision_applied: Optional[str] = None,
                 run_snapshot: Optional[dict] = None) -> bool:
    """Write the case, and optionally its applied marker, in one transaction.

    The run guard and every mutation share a single transaction, so a superseded
    worker cannot write into a newer run, and a crash cannot leave a visible
    applied result whose decision still looks pending. A zero-row conditional
    update marks nothing and reports failure.
    """
    case_data = case.model_dump(mode="json", by_alias=True)
    try:
        updated = db.execute(
            sa_text(
                "UPDATE cases SET workflow_status=:workflow_status, "
                "machine_assessment=:machine_assessment, resolution=:resolution, "
                "follow_up=:follow_up, updated_at=:updated_at, completed_at=:completed_at, "
                "run=:run, email=:email, documents=:documents, fields_data=:fields_data, "
                "review=:review, failure=:failure, history=:history, metrics=:metrics "
                "WHERE case_id=:case_id AND json_extract(run, '$.run_id')=:expected_run_id"
            ),
            {
                "workflow_status": case_data["workflow_status"],
                "machine_assessment": _json(case_data.get("machine_assessment")),
                "resolution": _json(case_data.get("resolution")),
                "follow_up": case_data.get("follow_up"),
                "updated_at": case_data["updated_at"],
                "completed_at": case_data.get("completed_at"),
                "run": _json(case_data["run"]),
                "email": _json(case_data["email"]),
                "documents": _json(case_data.get("documents", [])),
                "fields_data": _json(case_data.get("fields", [])),
                "review": _json(case_data.get("review")),
                "failure": _json(case_data.get("failure")),
                "history": _json(case_data.get("history", [])),
                "metrics": _json(case_data["metrics"]),
                "case_id": case.case_id,
                "expected_run_id": expected_run_id,
            },
        ).rowcount

        if updated == 0:
            # Superseded. Nothing is written, and no decision is marked applied.
            db.rollback()
            logger.info("case %s was superseded; the write was rejected", case.case_id)
            return False

        if mark_decision_applied is not None:
            marked = db.execute(
                sa_text(
                    "UPDATE accepted_decisions SET applied_at=:at "
                    "WHERE decision_id=:decision_id AND run_id=:run_id "
                    "AND applied_at IS NULL"
                ),
                {"at": case_data["updated_at"], "decision_id": mark_decision_applied,
                 "run_id": expected_run_id},
            ).rowcount
            if marked == 0:
                # Another worker applied it first; this whole attempt is discarded.
                db.rollback()
                logger.info("decision %s was already applied; discarding",
                            mark_decision_applied)
                return False

        if run_snapshot is not None:
            db.execute(
                sa_text(
                    "INSERT OR REPLACE INTO run_snapshots "
                    "(run_id, case_id, input_version, config_version, source_manifest, "
                    " classification, machine_state, config_manifest, created_at) "
                    "VALUES (:run_id, :case_id, :input_version, :config_version, "
                    "        :source_manifest, :classification, :machine_state, "
                    "        :config_manifest, :created_at)"
                ),
                run_snapshot,
            )

        db.commit()
    except Exception:
        db.rollback()
        raise
    db.expire_all()
    return True


def _json(value):
    return None if value is None else json.dumps(value)


# ---------------------------------------------------------------------------
# Initial processing
# ---------------------------------------------------------------------------

def process_case(case_id: str, job_id: str = None, job_run_id: str = None):
    """Run the automated pass and freeze its result."""
    db = database.SessionLocal()
    try:
        db_case = crud.get_case(db, case_id)
        if not db_case:
            raise PermanentProcessingError(f"case {case_id} does not exist")

        case = crud.map_db_to_schema(db_case)
        if job_run_id and case.run.run_id != job_run_id:
            logger.info("process_case: job %s is superseded, nothing to do", job_id)
            return
        if case.machine_assessment is not None:
            # This pass already finalized; a retry must not manufacture a second
            # assessment or a duplicate review.
            logger.info("process_case: case %s already has a frozen assessment", case_id)
            return

        expected_run_id = job_run_id or case.run.run_id

        try:
            snapshot, context, services, analysis = _run_analysis(case)
        except SourceDataIssue as exc:
            raise PermanentProcessingError(
                f"the input for {case_id} could not be mapped: {exc}"
            ) from exc

        now = _now()

        # Reload under the guard so the write reflects current state.
        db_case = crud.get_case(db, case_id)
        if db_case is None:
            return
        case = crud.map_db_to_schema(db_case)
        if case.run.run_id != expected_run_id or case.machine_assessment is not None:
            logger.info("process_case: %s changed while analyzing; discarding", case_id)
            return

        case.email.category = schemas.EmailCategory(analysis.category) if analysis.category else None
        case.email.classified_by = (schemas.ResolvedBy(analysis.classified_by)
                                    if analysis.classified_by else None)
        case.email.classification_reason = analysis.classification_reason or None
        case.email.received_at = snapshot.received_at

        case.run.input_version = analysis.input_version
        case.run.config_version = analysis.config_version

        case.documents = wire.document_refs_to_wire(analysis.documents)
        case.fields = wire.comparisons_to_wire(analysis.comparisons)
        case.machine_assessment = wire.assessment_to_wire(analysis, now)
        case.metrics = schemas.Metrics(
            ai_calls=analysis.ai_calls,
            ai_assisted_fields=analysis.ai_assisted_fields,
            processing_ms=analysis.processing_ms,
            est_ai_cost_usd=None,       # unknown cost is null, never a guessed zero
        )

        for event_type, summary in analysis.events:
            _event(case, event_type, summary, at=now)

        if analysis.review is not None:
            review_id = f"rev_{uuid.uuid4().hex[:8]}"
            case.review = wire.review_to_wire(
                analysis.review, review_id=review_id, case_id=case.case_id,
                run_id=case.run.run_id, created_at=now, documents=analysis.documents,
            )
            case.workflow_status = (schemas.WorkflowStatus.BLOCKED_EXTERNAL
                                    if analysis.review.blocks_externally
                                    else schemas.WorkflowStatus.AWAITING_HUMAN)
            case.follow_up = (schemas.FollowUp.AWAIT_EXTERNAL
                              if analysis.review.blocks_externally else schemas.FollowUp.NONE)
            case.completed_at = None
            _event(case, schemas.HistoryEventType.REVIEW_CREATED.value,
                   f"Review created: {analysis.review.scope}/{analysis.review.ui_mode}", at=now)
        else:
            case.review = None
            case.workflow_status = schemas.WorkflowStatus.COMPLETED
            status = analysis.assessment.status if analysis.assessment else "OK"
            case.follow_up = (schemas.FollowUp.CORRECTION_REQUIRED
                              if status == "MISMATCH" else schemas.FollowUp.NONE)
            case.completed_at = now
            _event(case, schemas.HistoryEventType.CASE_COMPLETED.value,
                   f"Case completed automatically with {status}", at=now)

        case.resolution = None   # no human action has been applied yet
        case.updated_at = now
        _commit_case(db, db_case, case, expected_run_id,
                     run_snapshot=save_run_snapshot(case, snapshot, analysis))
    except (RetryableProcessingError, PermanentProcessingError):
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Decision resumption
# ---------------------------------------------------------------------------

def apply_decision(case_id: str, job_id: str = None, job_run_id: str = None):
    """Apply the accepted decision bound to this job, then recompute dependencies."""
    db = database.SessionLocal()
    try:
        db_case = crud.get_case(db, case_id)
        if not db_case:
            raise PermanentProcessingError(f"case {case_id} does not exist")

        case = crud.map_db_to_schema(db_case)
        if job_run_id and case.run.run_id != job_run_id:
            logger.info("apply_decision: job %s is superseded, nothing to do", job_id)
            return
        expected_run_id = job_run_id or case.run.run_id

        record = _load_pending_decision(db, case_id, expected_run_id, job_id)
        if record is None:
            # Either already applied, or the record is genuinely missing. Neither
            # is repaired by inventing a value.
            if _has_applied_decision(db, case_id, expected_run_id, job_id):
                logger.info("apply_decision: job %s was already applied", job_id)
                return
            raise PermanentProcessingError(
                f"no accepted decision record is bound to job {job_id} on run {expected_run_id}"
            )

        # The original machine assessment must survive this resumption untouched.
        frozen_assessment = (case.machine_assessment.model_dump(mode="json")
                             if case.machine_assessment else None)

        try:
            state, context, snapshot, restored, applied_before = load_working_state(
                db, case, expected_run_id
            )
        except SourceDataIssue as exc:
            raise PermanentProcessingError(
                f"the input for {case_id} could not be re-read: {exc}"
            ) from exc

        decision = wire.decision_from_json(record.payload)
        result = apply_validated_decision(decision, state, context)

        now = _now()
        db_case = crud.get_case(db, case_id)
        if db_case is None:
            return
        case = crud.map_db_to_schema(db_case)
        if case.run.run_id != expected_run_id:
            logger.info("apply_decision: %s changed while applying; discarding", case_id)
            return

        overrides = _override_map(applied_before + [record])
        case.fields = wire.comparisons_to_wire(result.comparisons, overrides)

        # Public document roles follow the operational state, so a document a
        # person chose is shown in the role it now occupies. The original machine
        # interpretation stays in the run snapshot for audit.
        operational_documents = _documents_with_operational_roles(
            restored["documents"], result.state
        )
        case.documents = wire.document_refs_to_wire(operational_documents)

        if result.review is not None:
            review_id = f"rev_{uuid.uuid4().hex[:8]}"
            case.review = wire.review_to_wire(
                result.review, review_id=review_id, case_id=case.case_id,
                run_id=case.run.run_id, created_at=now,
                documents=operational_documents,
            )
            _event(case, schemas.HistoryEventType.REVIEW_CREATED.value,
                   f"Review created: {result.review.scope}/{result.review.ui_mode}", at=now)

        case.workflow_status = schemas.WorkflowStatus(result.workflow)
        case.follow_up = schemas.FollowUp(result.follow_up)
        case.completed_at = now if result.workflow == "COMPLETED" else None
        case.resolution = schemas.Resolution(
            review_id=decision.review_id,
            run_id=expected_run_id,
            action=schemas.DecisionAction(decision.action),
            value_source=(schemas.ValueSource(decision.value_origin)
                          if decision.value_origin else None),
            actor_id=decision.actor_id,
            channel=schemas.Channel(decision.channel),
            user_message=decision.user_message,
            resolved_at=now,
            final_status=schemas.MachineStatus(result.final_status),
            final_defect_fields=[schemas.CanonicalField(f) for f in result.final_defect_fields],
        )
        for event_type, summary in result.events:
            _event(case, event_type, summary, at=now)
        case.updated_at = now

        # Invariant: the frozen machine assessment is unchanged.
        current = case.machine_assessment.model_dump(mode="json") if case.machine_assessment else None
        if current != frozen_assessment:
            raise PermanentProcessingError(
                "the machine assessment changed during decision resumption"
            )

        # The case write and the applied marker share one transaction, so a
        # crash between them cannot produce a visible result that still looks
        # pending and would be applied a second time on retry.
        _commit_case(db, db_case, case, expected_run_id,
                     mark_decision_applied=record.decision_id)
    except (RetryableProcessingError, PermanentProcessingError):
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _documents_with_operational_roles(documents, state):
    """Document refs re-labelled from the current working roles.

    Exactly one document occupies each role, and the side that was not chosen is
    left as the automated pass found it.
    """
    import dataclasses

    if state is None or state.roles is None:
        return documents
    si_id = state.roles.si
    bl_id = state.roles.bl
    rebuilt = []
    for document in documents:
        if document.document_id == si_id:
            role = "SI"
        elif document.document_id == bl_id:
            role = "BL"
        elif document.role in ("SI", "BL"):
            # It held a role the human decision moved elsewhere.
            role = "OTHER"
        else:
            role = document.role
        rebuilt.append(dataclasses.replace(document, role=role))
    return rebuilt


def _load_pending_decision(db, case_id: str, run_id: str, job_id: Optional[str]):
    """The decision bound to this exact job, or ``None``.

    When a job id is supplied it must match exactly. An unknown, wrong or
    already-applied job never falls through to consume a different pending
    decision — that would let a stale retry apply work it was not accepted for.
    """
    query = (
        db.query(models.AcceptedDecisionModel)
        .filter(models.AcceptedDecisionModel.case_id == case_id)
        .filter(models.AcceptedDecisionModel.run_id == run_id)
        .filter(models.AcceptedDecisionModel.applied_at.is_(None))
    )
    if job_id is not None:
        return query.filter(models.AcceptedDecisionModel.job_id == job_id).first()
    # No job id: an explicit maintenance path, ordered and still run-bound.
    return query.order_by(models.AcceptedDecisionModel.sequence).first()


def _has_applied_decision(db, case_id: str, run_id: str, job_id: Optional[str]) -> bool:
    query = (
        db.query(models.AcceptedDecisionModel)
        .filter(models.AcceptedDecisionModel.case_id == case_id)
        .filter(models.AcceptedDecisionModel.run_id == run_id)
        .filter(models.AcceptedDecisionModel.applied_at.isnot(None))
    )
    if job_id is not None:
        query = query.filter(models.AcceptedDecisionModel.job_id == job_id)
    return query.first() is not None


def _applied_decisions(db, case_id: str, run_id: str) -> list:
    return (
        db.query(models.AcceptedDecisionModel)
        .filter(models.AcceptedDecisionModel.case_id == case_id)
        .filter(models.AcceptedDecisionModel.run_id == run_id)
        .filter(models.AcceptedDecisionModel.applied_at.isnot(None))
        .order_by(models.AcceptedDecisionModel.sequence)
        .all()
    )


def _override_map(records) -> dict:
    """Override confirmations keyed by (field, side), for the wire FieldValues."""
    from .intelligence.recomputation import OverrideConfirmation

    overrides: dict = {}
    for record in records:
        payload = record.payload
        confirmation = payload.get("override_confirmation")
        if not confirmation:
            continue
        key = (payload.get("target_field"), payload.get("target_side"))
        overrides.setdefault(key, []).append(OverrideConfirmation(
            review_id=confirmation["review_id"], run_id=confirmation["run_id"],
            field=confirmation["field"], side=confirmation["side"],
            proposed_value=confirmation["proposed_value"],
            confirmed=confirmation["confirmed"],
        ))
    return overrides
