from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from typing import List
from . import schemas, models, crud, worker
from .database import engine, get_db

# Create the database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Shipping Document Verification API", version="2.1.1")

@app.get("/health")
def health_check():
    return {"status": "OK", "version": "2.1.1"}

@app.get("/cases", response_model=List[schemas.CaseSummary])
def list_cases(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    cases = crud.get_cases(db, skip=skip, limit=limit)
    return [crud.map_case_to_summary(crud.map_db_to_schema(c)) for c in cases]

from fastapi import Response

@app.post("/cases", response_model=schemas.Case, status_code=status.HTTP_202_ACCEPTED)
def create_case(req: schemas.CreateCaseRequest, background_tasks: BackgroundTasks, response: Response, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=req.email_id)
    if db_case:
        # Contract §8: duplicate POST /cases for existing DEMO case should return 200 with current case
        response.status_code = status.HTTP_200_OK
        return crud.map_db_to_schema(db_case)
    
    # Create the case in PROCESSING state
    case = crud.create_initial_case(db, req.email_id)
    
    # Trigger the background worker
    background_tasks.add_task(worker.process_case, case.case_id)
    
    return case

@app.get("/cases/{case_id}", response_model=schemas.Case)
def read_case(case_id: str, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=case_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return crud.map_db_to_schema(db_case)

@app.get("/reviews", response_model=List[schemas.ReviewListItem])
def list_reviews(run_kind: schemas.RunKind = None, db: Session = Depends(get_db)):
    return crud.get_reviews(db, run_kind=run_kind)

@app.post("/reviews/{review_id}/notified", response_model=schemas.Review)
def review_notified(review_id: str, req: schemas.NotifiedRequest, db: Session = Depends(get_db)):
    # Find case with this review id
    cases = crud.get_cases(db)
    for c in cases:
        schema_case = crud.map_db_to_schema(c)
        if schema_case.review and schema_case.review.review_id == review_id:
            if schema_case.review.status != schemas.ReviewStatus.OPEN:
                raise HTTPException(status_code=409, detail="REVIEW_ALREADY_CLOSED")
            if schema_case.run.run_id != req.run_id:
                raise HTTPException(status_code=409, detail="STALE_RUN")
            
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            schema_case.review.notified_at = now
            
            schema_case.history.append(
                schemas.HistoryEvent(
                    event_id=f"evt_{now.replace(':','')}",
                    run_id=schema_case.run.run_id,
                    at=now,
                    type="REVIEW_NOTIFIED",
                    actor=schemas.Actor(kind="SYSTEM"),
                    summary="Review notification recorded"
                )
            )
            crud.update_case(db, c, schema_case)
            return schema_case.review
    
    raise HTTPException(status_code=404, detail="Review not found")

@app.post("/reviews/{review_id}/decision", status_code=status.HTTP_202_ACCEPTED)
def submit_decision(review_id: str, req: schemas.DecisionRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    cases = crud.get_cases(db)
    for c in cases:
        schema_case = crud.map_db_to_schema(c)
        if schema_case.review and schema_case.review.review_id == review_id:
            if schema_case.review.status != schemas.ReviewStatus.OPEN:
                raise HTTPException(status_code=409, detail="REVIEW_ALREADY_CLOSED")
            if schema_case.run.run_id != req.run_id:
                raise HTTPException(status_code=409, detail="STALE_RUN")
            
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            
            # Close the review
            schema_case.review.status = schemas.ReviewStatus.CLOSED
            schema_case.review.closed_at = now
            schema_case.review.close_reason = "DECISION_ACCEPTED"
            
            # Save resolution
            schema_case.resolution = schemas.Resolution(
                review_id=review_id,
                run_id=schema_case.run.run_id,
                action=req.action,
                value_source=schemas.ValueSource.MANUAL_OVERRIDE if req.override_confirmation else None,
                actor_id=req.actor_id,
                channel=req.channel,
                user_message=req.user_message,
                resolved_at=now,
                final_status=schemas.MachineStatus.NEEDS_REVIEW, # placeholder until worker recomputes
                final_defect_fields=[]
            )
            
            schema_case.workflow_status = schemas.WorkflowStatus.PROCESSING
            schema_case.history.append(
                schemas.HistoryEvent(
                    event_id=f"evt_{now.replace(':','')}",
                    run_id=schema_case.run.run_id,
                    at=now,
                    type="DECISION_ACCEPTED",
                    actor=schemas.Actor(kind="HUMAN", id=req.actor_id),
                    summary=f"Decision {req.action.value} accepted"
                )
            )
            crud.update_case(db, c, schema_case)
            
            # Recompute and resume processing
            background_tasks.add_task(worker.apply_decision, schema_case.case_id)
            
            return schema_case
    
    raise HTTPException(status_code=404, detail="Review not found")
