from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, status, Response
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timezone
import uuid
from . import schemas, models, crud, worker
from .database import engine, get_db

# Create the database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Shipping Document Verification API", version="2.1.1")

@app.get("/health")
def health_check():
    return {"status": "OK", "version": "2.1.1"}

@app.get("/ready")
def readiness_check():
    return {"status": "READY"}

@app.get("/cases", response_model=List[schemas.CaseSummary])
def list_cases(
    workflow_status: Optional[schemas.WorkflowStatus] = None,
    category: Optional[schemas.EmailCategory] = None,
    final_status: Optional[schemas.MachineStatus] = None,
    has_open_review: Optional[bool] = None,
    run_kind: Optional[schemas.RunKind] = None,
    skip: int = 0,
    limit: int = 100,
    db: Session = Depends(get_db)
):
    cases = crud.get_cases(db, skip=skip, limit=limit)
    summaries = [crud.map_case_to_summary(crud.map_db_to_schema(c)) for c in cases]
    
    # Apply filters
    if workflow_status:
        summaries = [s for s in summaries if s.workflow_status == workflow_status]
    if category:
        summaries = [s for s in summaries if s.category == category]
    if final_status:
        summaries = [s for s in summaries if s.final_status == final_status]
    if has_open_review is not None:
        summaries = [s for s in summaries if s.has_open_review == has_open_review]
    if run_kind:
        summaries = [s for s in summaries if s.run_kind == run_kind]
    
    return summaries

@app.post("/cases", response_model=schemas.Case, status_code=status.HTTP_202_ACCEPTED)
def create_case(req: schemas.CreateCaseRequest, background_tasks: BackgroundTasks, response: Response, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=req.email_id)
    if db_case:
        # Contract §8: duplicate POST /cases for existing DEMO case should return 200 with current case
        response.status_code = status.HTTP_200_OK
        return crud.map_db_to_schema(db_case)
    
    # Create the case in PROCESSING state
    case = crud.create_initial_case(db, req.email_id)
    
    # Create durable job
    job = crud.create_job(db, case.case_id, case.run.run_id, "PROCESS_CASE")
    
    # Trigger the background worker
    background_tasks.add_task(worker.process_case, case.case_id, job.job_id)
    
    return case

@app.get("/cases/{case_id}", response_model=schemas.Case)
def read_case(case_id: str, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=case_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return crud.map_db_to_schema(db_case)

@app.post("/cases/{case_id}/reprocess", response_model=schemas.Case, status_code=status.HTTP_202_ACCEPTED)
def reprocess_case(case_id: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=case_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    
    schema_case = crud.map_db_to_schema(db_case)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_run_id = f"run_{uuid.uuid4().hex[:8]}"
    
    # Supersede old OPEN review if any
    if schema_case.review and schema_case.review.status == schemas.ReviewStatus.OPEN:
        schema_case.review.status = schemas.ReviewStatus.CLOSED
        schema_case.review.closed_at = now
        schema_case.review.close_reason = "SUPERSEDED"
        schema_case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=schema_case.run.run_id,
                at=now,
                type="REVIEW_SUPERSEDED",
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Review superseded by reprocess"
            )
        )
    
    # Create new run
    schema_case.run = schemas.Run(
        run_id=new_run_id,
        kind=schemas.RunKind.DEMO,
        started_at=now,
        input_version="v1",
        config_version="v1",
        demo_safe=True
    )
    schema_case.workflow_status = schemas.WorkflowStatus.PROCESSING
    schema_case.machine_assessment = None
    schema_case.review = None
    schema_case.resolution = None
    schema_case.follow_up = schemas.FollowUp.NONE
    schema_case.failure = None
    schema_case.completed_at = None
    schema_case.updated_at = now
    
    schema_case.history.append(
        schemas.HistoryEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            run_id=new_run_id,
            at=now,
            type="CASE_REPROCESSED",
            actor=schemas.Actor(kind="SYSTEM", id=None),
            summary="Case reprocessed with new run"
        )
    )
    
    crud.update_case(db, db_case, schema_case)
    
    # Create durable job
    job = crud.create_job(db, schema_case.case_id, schema_case.run.run_id, "PROCESS_CASE")
    
    # Trigger the background worker
    background_tasks.add_task(worker.process_case, case_id, job.job_id)
    
    return schema_case

@app.get("/reviews", response_model=List[schemas.ReviewListItem])
def list_reviews(run_kind: Optional[schemas.RunKind] = None, db: Session = Depends(get_db)):
    return crud.get_reviews(db, run_kind=run_kind)

@app.post("/reviews/{review_id}/notified", response_model=schemas.Review)
def review_notified(review_id: str, req: schemas.NotifiedRequest, db: Session = Depends(get_db)):
    cases = crud.get_cases(db)
    for c in cases:
        schema_case = crud.map_db_to_schema(c)
        if schema_case.review and schema_case.review.review_id == review_id:
            if schema_case.review.status != schemas.ReviewStatus.OPEN:
                raise HTTPException(status_code=409, detail="REVIEW_ALREADY_CLOSED")
            if schema_case.run.run_id != req.run_id:
                raise HTTPException(status_code=409, detail="STALE_RUN")
            
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            schema_case.review.notified_at = now
            
            schema_case.history.append(
                schemas.HistoryEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
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
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    run_id=schema_case.run.run_id,
                    at=now,
                    type="DECISION_ACCEPTED",
                    actor=schemas.Actor(kind="HUMAN", id=req.actor_id),
                    summary=f"Decision {req.action.value} accepted"
                )
            )
            crud.update_case(db, c, schema_case)
            
            # Create durable job
            job = crud.create_job(db, schema_case.case_id, schema_case.run.run_id, "APPLY_DECISION")
            
            # Recompute and resume processing
            background_tasks.add_task(worker.apply_decision, schema_case.case_id, job.job_id)
            
            return schema_case
    
    raise HTTPException(status_code=404, detail="Review not found")

@app.get("/documents/{document_id}/content")
def get_document_content(document_id: str, db: Session = Depends(get_db)):
    # Placeholder — Person A will implement actual document storage/retrieval
    raise HTTPException(status_code=404, detail="Document not found")

@app.get("/stats", response_model=schemas.Stats)
def get_stats(run_kind: schemas.RunKind = schemas.RunKind.DEMO, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cases = crud.get_cases(db)
    
    by_category = {}
    by_machine_status = {}
    by_effective_status = {}
    by_workflow = {}
    unclassified = 0
    awaiting_human_now = 0
    auto_completed = 0
    ai_assisted_cases = 0
    ai_calls_total = 0
    processing_ms_list = []
    bl_total = 0
    bl_ok = 0
    bl_mismatch = 0
    bl_needs_review = 0
    
    for c in cases:
        case = crud.map_db_to_schema(c)
        
        # Filter by run_kind
        if case.run.kind != run_kind:
            continue
        
        # Category counts
        cat = case.email.category.value if case.email.category else None
        if cat:
            by_category[cat] = by_category.get(cat, 0) + 1
        else:
            unclassified += 1
        
        # Workflow counts
        wf = case.workflow_status.value
        by_workflow[wf] = by_workflow.get(wf, 0) + 1
        
        if case.workflow_status == schemas.WorkflowStatus.AWAITING_HUMAN:
            awaiting_human_now += 1
        
        # Machine status counts
        if case.machine_assessment:
            ms = case.machine_assessment.status.value
            by_machine_status[ms] = by_machine_status.get(ms, 0) + 1
        
        # Effective status
        effective = None
        if case.resolution:
            effective = case.resolution.final_status.value
        elif case.machine_assessment:
            effective = case.machine_assessment.status.value
        if effective:
            by_effective_status[effective] = by_effective_status.get(effective, 0) + 1
        
        # BL comparison stats
        if case.email.category == schemas.EmailCategory.BL_COMPARISON:
            bl_total += 1
            if effective == "OK":
                bl_ok += 1
            elif effective == "MISMATCH":
                bl_mismatch += 1
            elif effective == "NEEDS_REVIEW":
                bl_needs_review += 1
        
        # Auto-completed (no resolution = machine did it alone)
        if case.workflow_status == schemas.WorkflowStatus.COMPLETED and not case.resolution:
            auto_completed += 1
        
        # AI stats
        if case.metrics.ai_calls > 0:
            ai_assisted_cases += 1
        ai_calls_total += case.metrics.ai_calls
        if case.metrics.processing_ms is not None:
            processing_ms_list.append(case.metrics.processing_ms)
    
    avg_processing = None
    if processing_ms_list:
        avg_processing = sum(processing_ms_list) / len(processing_ms_list)
    
    return schemas.Stats(
        generated_at=now,
        run_kind=run_kind,
        total_cases=len(cases),
        unclassified=unclassified,
        by_category=by_category,
        bl_comparison=schemas.BLComparisonStats(
            total=bl_total, ok=bl_ok, mismatch=bl_mismatch, needs_review=bl_needs_review
        ),
        by_machine_status=by_machine_status,
        by_effective_status=by_effective_status,
        by_workflow=by_workflow,
        awaiting_human_now=awaiting_human_now,
        auto_completed=auto_completed,
        ai_assisted_cases=ai_assisted_cases,
        ai_calls_total=ai_calls_total,
        avg_processing_ms=avg_processing
    )
