import time
import uuid
import logging
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from . import crud, schemas, database

logger = logging.getLogger(__name__)


def _stale_run(db, case_id: str, expected_run_id: str) -> bool:
    """Return True if the case's current run_id no longer matches expected_run_id."""
    db_case = crud.get_case(db, case_id)
    if db_case is None:
        return True
    current = crud.map_db_to_schema(db_case)
    return current.run.run_id != expected_run_id


def _build_bl_fields(weight_raw="15,000 KGS", weight_norm=15000, is_weight_resolved=False):
    """Build all 7 canonical fields for BL_COMPARISON per Contract §6 Invariant 7."""
    fields = [
        schemas.FieldComparison(
            field=schemas.CanonicalField.shipper,
            si=schemas.FieldValue(
                raw="ACME SHIPPING LTD", normalized="acme shipping ltd",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            bl=schemas.FieldValue(
                raw="ACME SHIPPING LTD", normalized="acme shipping ltd",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            result=schemas.FieldResult.MATCH,
            compared_by=schemas.ResolvedBy.DETERMINISTIC
        ),
        schemas.FieldComparison(
            field=schemas.CanonicalField.consignee,
            si=schemas.FieldValue(
                raw="GLOBAL IMPORTS CORP", normalized="global imports corp",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            bl=schemas.FieldValue(
                raw="GLOBAL IMPORTS CORP", normalized="global imports corp",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            result=schemas.FieldResult.MATCH,
            compared_by=schemas.ResolvedBy.DETERMINISTIC
        ),
        schemas.FieldComparison(
            field=schemas.CanonicalField.notify_party,
            si=schemas.FieldValue(
                raw="SAME AS CONSIGNEE", normalized="global imports corp",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            bl=schemas.FieldValue(
                raw="SAME AS CONSIGNEE", normalized="global imports corp",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            result=schemas.FieldResult.MATCH,
            compared_by=schemas.ResolvedBy.DETERMINISTIC
        ),
        schemas.FieldComparison(
            field=schemas.CanonicalField.port_of_loading,
            si=schemas.FieldValue(
                raw="SINGAPORE", normalized="singapore",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            bl=schemas.FieldValue(
                raw="SINGAPORE", normalized="singapore",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            result=schemas.FieldResult.MATCH,
            compared_by=schemas.ResolvedBy.DETERMINISTIC
        ),
        schemas.FieldComparison(
            field=schemas.CanonicalField.port_of_discharge,
            si=schemas.FieldValue(
                raw="ROTTERDAM", normalized="rotterdam",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            bl=schemas.FieldValue(
                raw="ROTTERDAM", normalized="rotterdam",
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            result=schemas.FieldResult.MATCH,
            compared_by=schemas.ResolvedBy.DETERMINISTIC
        ),
        schemas.FieldComparison(
            field=schemas.CanonicalField.container_count,
            si=schemas.FieldValue(
                raw="2", normalized=2,
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            bl=schemas.FieldValue(
                raw="2", normalized=2,
                resolved_by=schemas.ResolvedBy.DETERMINISTIC,
                value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
                grounded=True
            ),
            result=schemas.FieldResult.MATCH,
            compared_by=schemas.ResolvedBy.DETERMINISTIC
        ),
    ]

    # 7th field: gross_weight_kg
    si_weight = schemas.FieldValue(
        raw="15,000 KGS", normalized=15000,
        resolved_by=schemas.ResolvedBy.DETERMINISTIC,
        value_origin=schemas.ValueOrigin.DOCUMENT_EXTRACTED,
        grounded=True
    )
    if is_weight_resolved:
        bl_weight = schemas.FieldValue(
            raw=str(weight_raw),
            normalized=weight_norm,
            resolved_by=schemas.ResolvedBy.HUMAN,
            value_origin=schemas.ValueOrigin.DOCUMENT_CONFIRMED,
            grounded=True
        )
        is_match = (weight_norm == 15000)
        result = schemas.FieldResult.MATCH if is_match else schemas.FieldResult.MISMATCH
        cause = None
    else:
        bl_weight = None
        result = schemas.FieldResult.NOT_COMPARABLE
        cause = schemas.NotComparableCause.UNREADABLE

    fields.append(schemas.FieldComparison(
        field=schemas.CanonicalField.gross_weight_kg,
        si=si_weight,
        bl=bl_weight,
        result=result,
        not_comparable_cause=cause,
        compared_by=schemas.ResolvedBy.DETERMINISTIC if not is_weight_resolved else schemas.ResolvedBy.HUMAN
    ))
    return fields


def process_case(case_id: str, job_id: str = None, job_run_id: str = None):
    """Worker stub: simulate classification and intake.

    Checks job_run_id == case.run.run_id before and after slow section.
    """
    db = database.SessionLocal()
    try:
        db_case = crud.get_case(db, case_id)
        if not db_case:
            raise ValueError(f"Case {case_id} not found")

        case = crud.map_db_to_schema(db_case)

        # Pre-work stale-run check
        if job_run_id and case.run.run_id != job_run_id:
            logger.info("process_case: job %s is stale, aborting", job_id)
            return

        # ── Fast simulated processing ─────────────────────────────────────────
        time.sleep(1)
        # ─────────────────────────────────────────────────────────────────────

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Post-work stale-run check
        if job_run_id and _stale_run(db, case_id, job_run_id):
            logger.info("process_case: run changed while processing %s, discarding results", case_id)
            return

        db_case = crud.get_case(db, case_id)
        case = crud.map_db_to_schema(db_case)

        case.email.category = schemas.EmailCategory.BL_COMPARISON
        case.email.classified_by = schemas.ResolvedBy.DETERMINISTIC

        case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=case.run.run_id,
                at=now,
                type=schemas.HistoryEventType.EMAIL_CLASSIFIED.value,
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Email classified as BL_COMPARISON",
            )
        )

        case.workflow_status = schemas.WorkflowStatus.AWAITING_HUMAN
        case.machine_assessment = schemas.MachineAssessment(
            status=schemas.MachineStatus.NEEDS_REVIEW,
            review_reason=schemas.ReviewReason.unreadable,
            has_defect=False,
            defect_fields=[],
            assessed_at=now
        )
        case.follow_up = schemas.FollowUp.NONE
        case.fields = _build_bl_fields(is_weight_resolved=False)

        review_id = f"rev_{uuid.uuid4().hex[:8]}"
        case.review = schemas.Review(**{
            "review_id": review_id,
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
            "allowed_actions": [schemas.DecisionAction.PROVIDE_VALUE, schemas.DecisionAction.ACKNOWLEDGE],
            "source_documents": [],
            "created_at": now,
            "notified_at": None,
            "closed_at": None,
            "close_reason": None
        })

        case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=case.run.run_id,
                at=now,
                type=schemas.HistoryEventType.REVIEW_CREATED.value,
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Review created for gross_weight_kg",
            )
        )

        case.updated_at = now
        case.completed_at = None

        crud.update_case(db, db_case, case)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def apply_decision(case_id: str, job_id: str = None, job_run_id: str = None):
    """Worker stub: recompute dependencies and settle case after human decision."""
    db = database.SessionLocal()
    try:
        db_case = crud.get_case(db, case_id)
        if not db_case:
            raise ValueError(f"Case {case_id} not found")

        case = crud.map_db_to_schema(db_case)

        # Pre-work stale-run check
        if job_run_id and case.run.run_id != job_run_id:
            logger.info("apply_decision: job %s is stale, aborting", job_id)
            return

        # ── Fast simulated processing ─────────────────────────────────────────
        time.sleep(1)
        # ─────────────────────────────────────────────────────────────────────

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Post-work stale-run check
        if job_run_id and _stale_run(db, case_id, job_run_id):
            logger.info("apply_decision: run changed while processing %s, discarding results", case_id)
            return

        db_case = crud.get_case(db, case_id)
        case = crud.map_db_to_schema(db_case)

        # Extract submitted value from latest DECISION_RECEIVED event or default to 15000
        submitted_raw = "15000"
        submitted_norm = 15000
        for ev in reversed(case.history):
            if ev.type == schemas.HistoryEventType.DECISION_RECEIVED.value and ev.details:
                if isinstance(ev.details, dict) and "value" in ev.details:
                    val = ev.details["value"]
                    if val is not None:
                        submitted_raw = str(val)
                        try:
                            # Parse numeric value
                            clean_val = submitted_raw.replace(",", "").replace("KGS", "").replace("kg", "").strip()
                            submitted_norm = float(clean_val)
                            if submitted_norm.is_integer():
                                submitted_norm = int(submitted_norm)
                        except ValueError:
                            submitted_norm = submitted_raw
                    break

        is_match = (submitted_norm == 15000)
        final_status = schemas.MachineStatus.OK if is_match else schemas.MachineStatus.MISMATCH

        if case.resolution:
            case.resolution.final_status = final_status
            case.resolution.final_defect_fields = [] if is_match else [schemas.CanonicalField.gross_weight_kg]

        case.workflow_status = schemas.WorkflowStatus.COMPLETED
        case.follow_up = schemas.FollowUp.NONE if is_match else schemas.FollowUp.CORRECTION_REQUIRED
        case.fields = _build_bl_fields(
            weight_raw=submitted_raw,
            weight_norm=submitted_norm,
            is_weight_resolved=True
        )
        case.updated_at = now
        case.completed_at = now

        case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=case.run.run_id,
                at=now,
                type=schemas.HistoryEventType.DECISION_APPLIED.value,
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Decision applied by worker",
            )
        )
        case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=case.run.run_id,
                at=now,
                type=schemas.HistoryEventType.CASE_COMPLETED.value,
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Case completed after decision applied",
            )
        )

        crud.update_case(db, db_case, case)
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
