import time
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from . import crud, schemas, database

def process_case(case_id: str, job_id: str = None):
    """
    Dummy asynchronous worker that simulates classification and extraction.
    Person A's logic will plug in here.
    """
    db = database.SessionLocal()
    try:
        if job_id:
            crud.update_job_status(db, job_id, "RUNNING")
            
        db_case = crud.get_case(db, case_id)
        if not db_case:
            if job_id:
                crud.update_job_status(db, job_id, "FAILED", error="Case not found")
            return
        
        case = crud.map_db_to_schema(db_case)
        
        # Simulate processing time
        time.sleep(2)
        
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Dummy classification
        case.email.category = schemas.EmailCategory.BL_COMPARISON
        case.email.classified_by = schemas.ResolvedBy.DETERMINISTIC
        
        # Dummy history event
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
        
        # In a real run, this would be either COMPLETED (if OK/MISMATCH) 
        # or AWAITING_HUMAN (if NEEDS_REVIEW).
        # We will mark it as NEEDS_REVIEW for now to test the review endpoints.
        case.workflow_status = schemas.WorkflowStatus.AWAITING_HUMAN
        case.machine_assessment = schemas.MachineAssessment(
            status=schemas.MachineStatus.NEEDS_REVIEW,
            review_reason=schemas.ReviewReason.unreadable,
            has_defect=False,
            defect_fields=[schemas.CanonicalField.gross_weight_kg],
            assessed_at=now
        )
        
        # Create a mock review
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
        
        if job_id:
            crud.update_job_status(db, job_id, "COMPLETED")
    except Exception as e:
        if job_id:
            crud.update_job_status(db, job_id, "FAILED", error=str(e))
        raise
    finally:
        db.close()

def apply_decision(case_id: str, job_id: str = None):
    """
    Dummy asynchronous worker that simulates recomputing dependencies 
    after a human resolves a NEEDS_REVIEW case.
    """
    db = database.SessionLocal()
    try:
        if job_id:
            crud.update_job_status(db, job_id, "RUNNING")
            
        db_case = crud.get_case(db, case_id)
        if not db_case:
            if job_id:
                crud.update_job_status(db, job_id, "FAILED", error="Case not found")
            return
        
        case = crud.map_db_to_schema(db_case)
        
        # Simulate processing time for recomputation
        time.sleep(2)
        
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        
        # Update resolution to be final
        if case.resolution:
            case.resolution.final_status = schemas.MachineStatus.OK
            
        case.workflow_status = schemas.WorkflowStatus.COMPLETED
        case.updated_at = now
        case.completed_at = now
        
        case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=case.run.run_id,
                at=now,
                type="CASE_COMPLETED",
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Decision applied and case completed",
            )
        )
        
        crud.update_case(db, db_case, case)
        
        if job_id:
            crud.update_job_status(db, job_id, "COMPLETED")
    except Exception as e:
        if job_id:
            crud.update_job_status(db, job_id, "FAILED", error=str(e))
        raise
    finally:
        db.close()
