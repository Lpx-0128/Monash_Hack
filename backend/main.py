from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Response, Request, APIRouter
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional
from datetime import datetime, timezone
import uuid
from . import schemas, models, crud, worker
from .database import engine, get_db, SessionLocal

# Create the database tables
models.Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the worker loop exactly once at startup — never as an import side effect."""
    from .worker_loop import start_worker_thread
    start_worker_thread()
    yield


app = FastAPI(title="Shipping Document Verification API", version="2.1.1", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Error response envelope — contract §7
# ---------------------------------------------------------------------------

_HTTP_TO_CODE = {
    400: "BAD_REQUEST",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "UNPROCESSABLE",
    500: "INTERNAL_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

# Contract-defined error codes that may appear verbatim in detail
_CONTRACT_CODES = {
    "STALE_RUN", "REVIEW_ALREADY_CLOSED", "CASE_NOT_FOUND", "REVIEW_NOT_FOUND",
    "NOT_FOUND", "BAD_REQUEST", "CONFLICT", "INTERNAL_ERROR",
    "SERVICE_UNAVAILABLE", "UNPROCESSABLE",
}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    detail = exc.detail or ""
    if detail in _CONTRACT_CODES:
        code = detail
        message = detail.replace("_", " ").title()
    else:
        code = _HTTP_TO_CODE.get(exc.status_code, "INTERNAL_ERROR")
        message = detail if detail else code
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": "UNPROCESSABLE", "message": str(exc)}}
    )


# ---------------------------------------------------------------------------
# Health / ready at the root (contract §5 — cloud probes hit bare paths)
# ---------------------------------------------------------------------------

@app.get("/health")
def health_check():
    return {"status": "OK", "version": "2.1.1"}


@app.get("/ready")
def readiness_check():
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return {"status": "READY"}
    except Exception:
        raise HTTPException(status_code=503, detail="SERVICE_UNAVAILABLE")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API router — all business routes under /api/v1
# ---------------------------------------------------------------------------

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/cases", response_model=List[schemas.CaseSummary])
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
    # Fetch all, filter before slicing (DB-level filter is future work)
    all_cases = crud.get_cases(db, skip=0, limit=10_000)
    summaries = [crud.map_case_to_summary(crud.map_db_to_schema(c)) for c in all_cases]

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

    return summaries[skip: skip + limit]


@api_router.post("/cases", response_model=schemas.Case, status_code=status.HTTP_202_ACCEPTED)
def create_case(req: schemas.CreateCaseRequest, response: Response, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=req.email_id)
    if db_case:
        response.status_code = status.HTTP_200_OK
        return crud.map_db_to_schema(db_case)

    # Create case and job in one transaction so no crash can strand a case in PROCESSING
    case = crud.create_case_with_job(db, req.email_id)
    return case


@api_router.get("/cases/{case_id}", response_model=schemas.Case)
def read_case(case_id: str, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=case_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")
    return crud.map_db_to_schema(db_case)


@api_router.post("/cases/{case_id}/reprocess", response_model=schemas.Case, status_code=status.HTTP_202_ACCEPTED)
def reprocess_case(case_id: str, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=case_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail="CASE_NOT_FOUND")

    schema_case = crud.map_db_to_schema(db_case)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_run_id = f"run_{uuid.uuid4().hex[:8]}"

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

    # Cancel stale PENDING/RUNNING jobs for this case before creating the new one,
    # so the old worker cannot run against the new run.
    crud.cancel_pending_jobs_for_case(db, case_id)

    crud.update_case(db, db_case, schema_case)
    crud.create_job(db, schema_case.case_id, schema_case.run.run_id, "PROCESS_CASE")
    return schema_case


@api_router.get("/reviews", response_model=List[schemas.ReviewListItem])
def list_reviews(run_kind: Optional[schemas.RunKind] = None, db: Session = Depends(get_db)):
    return crud.get_reviews(db, run_kind=run_kind)


@api_router.post("/reviews/{review_id}/notified", response_model=schemas.Review)
def review_notified(review_id: str, req: schemas.NotifiedRequest, db: Session = Depends(get_db)):
    cases = crud.get_cases(db)
    for c in cases:
        schema_case = crud.map_db_to_schema(c)
        if schema_case.review and schema_case.review.review_id == review_id:
            # Idempotent: already notified → return current review silently
            if schema_case.review.notified_at is not None:
                return schema_case.review
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

    raise HTTPException(status_code=404, detail="REVIEW_NOT_FOUND")


@api_router.post("/reviews/{review_id}/decision", status_code=status.HTTP_202_ACCEPTED)
def submit_decision(review_id: str, req: schemas.DecisionRequest, db: Session = Depends(get_db)):
    cases = crud.get_cases(db)
    for c in cases:
        schema_case = crud.map_db_to_schema(c)
        if schema_case.review and schema_case.review.review_id == review_id:
            if schema_case.review.status != schemas.ReviewStatus.OPEN:
                raise HTTPException(status_code=409, detail="REVIEW_ALREADY_CLOSED")
            if schema_case.run.run_id != req.run_id:
                raise HTTPException(status_code=409, detail="STALE_RUN")

            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            schema_case.review.status = schemas.ReviewStatus.CLOSED
            schema_case.review.closed_at = now
            schema_case.review.close_reason = "DECISION_ACCEPTED"

            # Resolution stored; final_status set by worker after it applies the decision
            schema_case.resolution = schemas.Resolution(
                review_id=review_id,
                run_id=schema_case.run.run_id,
                action=req.action,
                value_source=schemas.ValueSource.MANUAL_OVERRIDE if req.override_confirmation else None,
                actor_id=req.actor_id,
                channel=req.channel,
                user_message=req.user_message,
                resolved_at=now,
                final_status=schemas.MachineStatus.NEEDS_REVIEW,  # worker overwrites this
                final_defect_fields=[]
            )

            schema_case.workflow_status = schemas.WorkflowStatus.PROCESSING

            # Contract event names: DECISION_RECEIVED on intake, DECISION_QUEUED once enqueued
            schema_case.history.append(
                schemas.HistoryEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    run_id=schema_case.run.run_id,
                    at=now,
                    type="DECISION_RECEIVED",
                    actor=schemas.Actor(kind="HUMAN", id=req.actor_id),
                    summary=f"Decision {req.action.value} received"
                )
            )
            schema_case.history.append(
                schemas.HistoryEvent(
                    event_id=f"evt_{uuid.uuid4().hex[:8]}",
                    run_id=schema_case.run.run_id,
                    at=now,
                    type="DECISION_QUEUED",
                    actor=schemas.Actor(kind="SYSTEM", id=None),
                    summary="Decision queued for application by worker"
                )
            )

            # Case update and job insert in one transaction
            crud.update_case_and_create_job(db, c, schema_case, "APPLY_DECISION")
            return schema_case

    raise HTTPException(status_code=404, detail="REVIEW_NOT_FOUND")


@api_router.get("/documents/{document_id}/content")
def get_document_content(document_id: str, db: Session = Depends(get_db)):
    # Placeholder — Person A will implement actual document storage/retrieval
    raise HTTPException(status_code=404, detail="NOT_FOUND")


@api_router.get("/stats", response_model=schemas.Stats)
def get_stats(run_kind: schemas.RunKind = schemas.RunKind.DEMO, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cases = crud.get_cases(db, skip=0, limit=10_000)

    # Pre-populate all enum keys with 0 so frontend always sees every key
    by_category = {e.value: 0 for e in schemas.EmailCategory}
    by_machine_status = {e.value: 0 for e in schemas.MachineStatus}
    by_effective_status = {e.value: 0 for e in schemas.MachineStatus}
    by_workflow = {e.value: 0 for e in schemas.WorkflowStatus}

    total_filtered = 0
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
        if case.run.kind != run_kind:
            continue
        total_filtered += 1

        cat = case.email.category.value if case.email.category else None
        if cat:
            by_category[cat] = by_category.get(cat, 0) + 1
        else:
            unclassified += 1

        wf = case.workflow_status.value
        by_workflow[wf] = by_workflow.get(wf, 0) + 1

        if case.workflow_status == schemas.WorkflowStatus.AWAITING_HUMAN:
            awaiting_human_now += 1

        if case.machine_assessment:
            ms = case.machine_assessment.status.value
            by_machine_status[ms] = by_machine_status.get(ms, 0) + 1

        effective = None
        if case.resolution:
            effective = case.resolution.final_status.value
        elif case.machine_assessment:
            effective = case.machine_assessment.status.value
        if effective:
            by_effective_status[effective] = by_effective_status.get(effective, 0) + 1

        if case.email.category == schemas.EmailCategory.BL_COMPARISON:
            bl_total += 1
            if effective == "OK":
                bl_ok += 1
            elif effective == "MISMATCH":
                bl_mismatch += 1
            elif effective == "NEEDS_REVIEW":
                bl_needs_review += 1

        if case.workflow_status == schemas.WorkflowStatus.COMPLETED and not case.resolution:
            auto_completed += 1

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
        total_cases=total_filtered,
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


# Mount the versioned router
app.include_router(api_router)
