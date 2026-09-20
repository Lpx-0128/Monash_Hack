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
from .intelligence.pipeline import AnalysisContext, IntelligenceServices, analyze_case
from .intelligence.recomputation import (
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


def _build_services() -> IntelligenceServices:
    config = crud.intelligence_config()
    return IntelligenceServices(
        registries=crud.intelligence_registries(),
        model=ai_module.build_model_client(config.ai),
        budget=ai_module.CallBudget(limit=config.ai.max_calls_per_run),
    )


def _run_analysis(case: schemas.Case):
    """Ingest and analyze outside any database write transaction."""
    snapshot = crud.load_input_snapshot(case.email.email_id, case.run.kind)
    context = _build_context(case)
    services = _build_services()
    analysis = analyze_case(snapshot, context, services)
    return snapshot, context, services, analysis


def _commit_case(db, db_case, case: schemas.Case, expected_run_id: str) -> bool:
    """Write the case only while it still belongs to ``expected_run_id``.

    The guard and the mutation share one transaction, so a superseded worker
    cannot write into a newer run.
    """
    case_data = case.model_dump(mode="json", by_alias=True)
    updated = db.execute(
        sa_text(
            "UPDATE cases SET workflow_status=:workflow_status, machine_assessment=:machine_assessment, "
            "resolution=:resolution, follow_up=:follow_up, updated_at=:updated_at, "
            "completed_at=:completed_at, email=:email, documents=:documents, "
            "fields_data=:fields_data, review=:review, failure=:failure, history=:history, "
            "metrics=:metrics "
            "WHERE case_id=:case_id AND json_extract(run, '$.run_id')=:expected_run_id"
        ),
        {
            "workflow_status": case_data["workflow_status"],
            "machine_assessment": _json(case_data.get("machine_assessment")),
            "resolution": _json(case_data.get("resolution")),
            "follow_up": case_data.get("follow_up"),
            "updated_at": case_data["updated_at"],
            "completed_at": case_data.get("completed_at"),
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
    db.commit()
    if updated == 0:
        logger.info("case %s was superseded; the write was rejected", case.case_id)
        return False
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
        _commit_case(db, db_case, case, expected_run_id)
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

        applied_before = _applied_decisions(db, case_id, expected_run_id)

        # The original machine assessment must survive this resumption untouched.
        frozen_assessment = (case.machine_assessment.model_dump(mode="json")
                             if case.machine_assessment else None)

        try:
            snapshot, context, services, analysis = _run_analysis(case)
        except SourceDataIssue as exc:
            raise PermanentProcessingError(
                f"the input for {case_id} could not be re-read: {exc}"
            ) from exc

        registry = crud.intelligence_registries().get(snapshot.registry_kind)
        state = working_state_from_analysis(
            analysis, snapshot, registry.numeric_convention() if registry else ""
        )

        # Replay decisions already applied to this run, in acceptance order, so
        # the working state matches what was durably committed before.
        for earlier in applied_before:
            state = apply_validated_decision(
                wire.decision_from_json(earlier.payload), state, context
            ).state

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

        if result.review is not None:
            review_id = f"rev_{uuid.uuid4().hex[:8]}"
            case.review = wire.review_to_wire(
                result.review, review_id=review_id, case_id=case.case_id,
                run_id=case.run.run_id, created_at=now, documents=analysis.documents,
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

        if _commit_case(db, db_case, case, expected_run_id):
            _mark_decision_applied(db, record.decision_id, now)
    except (RetryableProcessingError, PermanentProcessingError):
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def _load_pending_decision(db, case_id: str, run_id: str, job_id: Optional[str]):
    query = (
        db.query(models.AcceptedDecisionModel)
        .filter(models.AcceptedDecisionModel.case_id == case_id)
        .filter(models.AcceptedDecisionModel.run_id == run_id)
        .filter(models.AcceptedDecisionModel.applied_at.is_(None))
    )
    if job_id:
        bound = query.filter(models.AcceptedDecisionModel.job_id == job_id).first()
        if bound is not None:
            return bound
    return query.order_by(models.AcceptedDecisionModel.sequence).first()


def _has_applied_decision(db, case_id: str, run_id: str, job_id: Optional[str]) -> bool:
    query = (
        db.query(models.AcceptedDecisionModel)
        .filter(models.AcceptedDecisionModel.case_id == case_id)
        .filter(models.AcceptedDecisionModel.run_id == run_id)
        .filter(models.AcceptedDecisionModel.applied_at.isnot(None))
    )
    if job_id:
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


def _mark_decision_applied(db, decision_id: str, at: str) -> None:
    db.execute(
        sa_text(
            "UPDATE accepted_decisions SET applied_at=:at "
            "WHERE decision_id=:decision_id AND applied_at IS NULL"
        ),
        {"at": at, "decision_id": decision_id},
    )
    db.commit()


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
