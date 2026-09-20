import time
import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy import text
from sqlalchemy.orm import Session
from . import crud, schemas, database

logger = logging.getLogger(__name__)


def _stale_run(db, case_id: str, expected_run_id: str) -> bool:
    """Return True if the case's current run_id no longer matches expected_run_id.

    Called before and after the slow part of a worker function to detect that a
    reprocess happened while this job was in flight.
    """
    db_case = crud.get_case(db, case_id)
    if db_case is None:
        return True
    current = crud.map_db_to_schema(db_case)
    return current.run.run_id != expected_run_id


def process_case(case_id: str, job_id: str = None, job_run_id: str = None):
    """Dummy worker: simulate classification and create a review.

    Checks job_run_id == case.run.run_id before and after the slow section so a
    stale job never writes its results to a case that has moved on to a new run.
    The loop marks the job RUNNING before calling here; we never touch RUNNING
    ourselves, and we raise on stale so the loop can guard the COMPLETED update.
    """
    db = database.SessionLocal()
    try:
        db_case = crud.get_case(db, case_id)
        if not db_case:
            raise ValueError(f"Case {case_id} not found")

        case = crud.map_db_to_schema(db_case)

        # Pre-work stale-run check
        if job_run_id and case.run.run_id != job_run_id:
            logger.info("process_case: job %s is stale (job run %s, case run %s), aborting",
                        job_id, job_run_id, case.run.run_id)
            return  # loop's COMPLETED guard will discard this job

        # ── Simulate processing (Person A replaces this) ──────────────────────
        time.sleep(2)
        # ─────────────────────────────────────────────────────────────────────

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Post-work stale-run check (reprocess could have happened during sleep)
        if job_run_id and _stale_run(db, case_id, job_run_id):
            logger.info("process_case: run changed while processing %s, discarding results", case_id)
            return

        # Re-fetch to get the freshest version after the sleep
        db_case = crud.get_case(db, case_id)
        case = crud.map_db_to_schema(db_case)

        case.email.category = schemas.EmailCategory.BL_COMPARISON
        case.email.classified_by = schemas.ResolvedBy.DETERMINISTIC

        case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=case.run.run_id,
                at=now,
                type="EMAIL_CLASSIFIED",
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Simulated email classification",
            )
        )

        case.workflow_status = schemas.WorkflowStatus.AWAITING_HUMAN
        case.machine_assessment = schemas.MachineAssessment(
            status=schemas.MachineStatus.NEEDS_REVIEW,
            review_reason=schemas.ReviewReason.unreadable,
            has_defect=False,
            defect_fields=[],   # NEEDS_REVIEW must not set defect_fields
            assessed_at=now
        )

        case.review = schemas.Review(**{
            "review_id": f"rev_{uuid.uuid4().hex[:8]}",
            "case_id": case.case_id,
            "run_id": case.run.run_id,
            "status": schemas.ReviewStatus.OPEN,
            "scope": schemas.ReviewScope.FIELD,
            "ui_mode": schemas.ReviewUiMode.VALUE_INPUT,
            "reason": schemas.ReviewReason.unreadable,
            "field": schemas.CanonicalField.gross_weight_kg,
            "side": schemas.Side.BL,
            "target_role": None,
            "question": "Please enter the gross weight in kg from the BL document.",
            "context_summary": "The AI could not read the gross weight on the scanned document.",
            "options": None,
            "allowed_actions": [schemas.DecisionAction.PROVIDE_VALUE],
            "source_documents": [],
            "created_at": now,
            "notified_at": None,
            "closed_at": None,
            "close_reason": None
        })

        case.updated_at = now
        case.completed_at = None

        crud.update_case(db, db_case, case)
        # Do NOT update job status here — the loop does it with a guarded UPDATE
    except Exception:
        raise
    finally:
        db.close()


def apply_decision(case_id: str, job_id: str = None, job_run_id: str = None):
    """Dummy worker: simulate recomputing dependencies after a human decision.

    Emits DECISION_APPLIED when it actually applies the decision, so history
    reflects the real moment of application rather than the moment of intake.
    """
    db = database.SessionLocal()
    try:
        db_case = crud.get_case(db, case_id)
        if not db_case:
            raise ValueError(f"Case {case_id} not found")

        case = crud.map_db_to_schema(db_case)

        # Pre-work stale-run check
        if job_run_id and case.run.run_id != job_run_id:
            logger.info("apply_decision: job %s is stale (job run %s, case run %s), aborting",
                        job_id, job_run_id, case.run.run_id)
            return

        # ── Simulate recomputation (Person A replaces this) ───────────────────
        time.sleep(2)
        # ─────────────────────────────────────────────────────────────────────

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Post-work stale-run check
        if job_run_id and _stale_run(db, case_id, job_run_id):
            logger.info("apply_decision: run changed while processing %s, discarding results", case_id)
            return

        # Re-fetch fresh
        db_case = crud.get_case(db, case_id)
        case = crud.map_db_to_schema(db_case)

        if case.resolution:
            case.resolution.final_status = schemas.MachineStatus.OK

        case.workflow_status = schemas.WorkflowStatus.COMPLETED
        case.updated_at = now
        case.completed_at = now

        # DECISION_APPLIED emitted here — when the worker actually applies the decision
        case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=case.run.run_id,
                at=now,
                type="DECISION_APPLIED",
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Decision applied by worker",
            )
        )
        case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=case.run.run_id,
                at=now,
                type="CASE_COMPLETED",
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Case completed after decision applied",
            )
        )

        crud.update_case(db, db_case, case)
        # Do NOT update job status here — the loop does it with a guarded UPDATE
    except Exception:
        raise
    finally:
        db.close()
