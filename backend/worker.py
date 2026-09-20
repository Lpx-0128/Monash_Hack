import time
import uuid
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from . import crud, schemas, database

def process_case(case_id: str):
    """
    Dummy asynchronous worker that simulates classification and extraction.
    Person A's logic will plug in here.
    """
    db = database.SessionLocal()
    try:
        db_case = crud.get_case(db, case_id)
        if not db_case:
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
        # We will just mark it as COMPLETED for now to show progression.
        case.workflow_status = schemas.WorkflowStatus.COMPLETED
        case.machine_assessment = schemas.MachineAssessment(
            status=schemas.MachineStatus.OK,
            has_defect=False,
            defect_fields=[],
            assessed_at=now
        )
        case.updated_at = now
        case.completed_at = now
        
        crud.update_case(db, db_case, case)
    finally:
        db.close()
