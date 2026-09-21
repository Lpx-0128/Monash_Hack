from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, status, Response, Request, Header, APIRouter
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional, Any
from datetime import datetime, timezone
import uuid
from . import schemas, models, crud, worker
from .database import engine, get_db, SessionLocal, init_db
from .worker_loop import start_worker_thread, stop_worker_thread

# Initialize database schema
init_db()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the worker loop at startup and stop it on shutdown."""
    start_worker_thread()
    yield
    stop_worker_thread()


app = FastAPI(title="Shipping Document Verification API", version="2.1.1", lifespan=lifespan)

# ---------------------------------------------------------------------------
# Error response envelope — Contract §7 & §8
# ---------------------------------------------------------------------------

_HTTP_TO_CODE = {
    400: schemas.ErrorCode.INVALID_VALUE.value,
    401: schemas.ErrorCode.UNAUTHORIZED.value,
    403: schemas.ErrorCode.FORBIDDEN.value,
    404: schemas.ErrorCode.NOT_FOUND.value,
    409: schemas.ErrorCode.REVIEW_ALREADY_CLOSED.value,
    422: schemas.ErrorCode.ACTION_NOT_ALLOWED.value,
    429: schemas.ErrorCode.RATE_LIMITED.value,
    500: schemas.ErrorCode.INTERNAL.value,
    503: schemas.ErrorCode.INTERNAL.value,
}

_VALID_ERROR_CODES = {e.value for e in schemas.ErrorCode}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if isinstance(exc.detail, dict):
        code = exc.detail.get("code", _HTTP_TO_CODE.get(exc.status_code, schemas.ErrorCode.INTERNAL.value))
        message = exc.detail.get("message", code)
        content = {"error": {"code": code, "message": message}}
        if "current_case" in exc.detail:
            content["error"]["current_case"] = exc.detail["current_case"]
        return JSONResponse(status_code=exc.status_code, content=content)

    detail_str = str(exc.detail or "")
    if detail_str in _VALID_ERROR_CODES:
        code = detail_str
        message = detail_str.replace("_", " ").title()
    else:
        code = _HTTP_TO_CODE.get(exc.status_code, schemas.ErrorCode.INTERNAL.value)
        message = detail_str if detail_str else code

    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": code, "message": message}}
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": {"code": schemas.ErrorCode.ACTION_NOT_ALLOWED.value, "message": str(exc)}}
    )


# ---------------------------------------------------------------------------
# Health / ready at root (Contract §8)
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
        raise HTTPException(status_code=503, detail=schemas.ErrorCode.INTERNAL.value)
    finally:
        db.close()


# ---------------------------------------------------------------------------
# API router — all business routes under /api/v1
# ---------------------------------------------------------------------------

api_router = APIRouter(prefix="/api/v1")


def _get_caller_scope(x_run_kind: Optional[str]) -> schemas.RunKind:
    """Server-side scope enforcement: EVAL requires explicit X-Run-Kind: EVAL header."""
    return schemas.RunKind.EVAL if x_run_kind == "EVAL" else schemas.RunKind.DEMO


@api_router.get("/cases", response_model=List[schemas.CaseSummary])
def list_cases(
    workflow_status: Optional[schemas.WorkflowStatus] = None,
    category: Optional[schemas.EmailCategory] = None,
    final_status: Optional[schemas.MachineStatus] = None,
    has_open_review: Optional[bool] = None,
    run_kind: Optional[schemas.RunKind] = None,
    skip: int = 0,
    limit: int = 100,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    caller_scope = _get_caller_scope(x_run_kind)
    # A public caller cannot widen scope to EVAL
    effective_run_kind = caller_scope if caller_scope == schemas.RunKind.DEMO else (run_kind or caller_scope)

    all_cases = crud.get_cases(db, skip=0, limit=10_000)
    summaries = [crud.map_case_to_summary(crud.map_db_to_schema(c)) for c in all_cases]

    # Enforce scope
    summaries = [s for s in summaries if s.run_kind == effective_run_kind]

    if workflow_status:
        summaries = [s for s in summaries if s.workflow_status == workflow_status]
    if category:
        summaries = [s for s in summaries if s.category == category]
    if final_status:
        summaries = [s for s in summaries if s.final_status == final_status]
    if has_open_review is not None:
        summaries = [s for s in summaries if s.has_open_review == has_open_review]

    return summaries[skip: skip + limit]


@api_router.post("/cases", response_model=schemas.Case, status_code=status.HTTP_202_ACCEPTED)
def create_case(
    req: schemas.CreateCaseRequest,
    response: Response,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    run_kind = _get_caller_scope(x_run_kind)
    db_case = crud.get_case(db, case_id=req.email_id)
    if db_case:
        existing = crud.map_db_to_schema(db_case)
        if existing.run.kind == schemas.RunKind.EVAL and run_kind != schemas.RunKind.EVAL:
            # Conceal existence of EVAL case from public scope per AC-07
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=schemas.ErrorCode.NOT_FOUND.value)
        else:
            response.status_code = status.HTTP_200_OK
            return existing

    case = crud.create_case_with_job(db, req.email_id, run_kind=run_kind)
    return case


@api_router.post("/cases/batch", response_model=schemas.BatchCreateCasesResponse, status_code=status.HTTP_202_ACCEPTED)
def batch_create_cases(
    req: schemas.BatchCreateCasesRequest,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    run_kind = _get_caller_scope(x_run_kind)
    created_count = 0
    existing_count = 0
    case_ids = []

    for email_id in req.email_ids:
        email_id = str(email_id).strip()
        if not email_id:
            continue
        db_case = crud.get_case(db, case_id=email_id)
        if db_case:
            existing = crud.map_db_to_schema(db_case)
            if existing.run.kind == schemas.RunKind.EVAL and run_kind != schemas.RunKind.EVAL:
                # Conceal existence of EVAL case from public callers per AC-07
                continue
            existing_count += 1
            case_ids.append(email_id)
        else:
            crud.create_case_with_job(db, email_id, run_kind=run_kind)
            created_count += 1
            case_ids.append(email_id)

    return schemas.BatchCreateCasesResponse(
        total_requested=len(req.email_ids),
        created=created_count,
        existing=existing_count,
        case_ids=case_ids
    )


@api_router.get("/cases/{case_id}", response_model=schemas.Case)
def read_case(
    case_id: str,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    db_case = crud.get_case(db, case_id=case_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    case = crud.map_db_to_schema(db_case)
    caller_scope = _get_caller_scope(x_run_kind)
    # AC-07: Public request for EVAL case returns 404 (conceals existence)
    if case.run.kind == schemas.RunKind.EVAL and caller_scope != schemas.RunKind.EVAL:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    return case


@api_router.post("/cases/{case_id}/reprocess", response_model=schemas.Case, status_code=status.HTTP_202_ACCEPTED)
def reprocess_case(
    case_id: str,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    db_case = crud.get_case(db, case_id=case_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    caller_scope = _get_caller_scope(x_run_kind)
    schema_case = crud.map_db_to_schema(db_case)
    if schema_case.run.kind == schemas.RunKind.EVAL and caller_scope != schemas.RunKind.EVAL:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

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
                type=schemas.HistoryEventType.REVIEW_SUPERSEDED.value,
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Review superseded by reprocess"
            )
        )

    schema_case.run = schemas.Run(
        run_id=new_run_id,
        kind=caller_scope,
        started_at=now,
        input_version="v1",
        config_version="v1",
        demo_safe=(caller_scope == schemas.RunKind.DEMO)
    )
    schema_case.workflow_status = schemas.WorkflowStatus.PROCESSING
    schema_case.machine_assessment = None
    schema_case.review = None
    schema_case.resolution = None
    schema_case.follow_up = schemas.FollowUp.NONE
    schema_case.failure = None
    schema_case.completed_at = None
    schema_case.updated_at = now
    schema_case.fields = []

    schema_case.history.append(
        schemas.HistoryEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            run_id=new_run_id,
            at=now,
            type=schemas.HistoryEventType.CASE_REPROCESSED.value,
            actor=schemas.Actor(kind="SYSTEM", id=None),
            summary="Case reprocessed with new run"
        )
    )

    return crud.reprocess_case_atomic(db, db_case, schema_case)


@api_router.get("/reviews", response_model=List[schemas.ReviewListItem])
def list_reviews(
    status: Optional[schemas.ReviewStatus] = schemas.ReviewStatus.OPEN,
    notified: Optional[bool] = None,
    run_kind: Optional[schemas.RunKind] = None,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    caller_scope = _get_caller_scope(x_run_kind)
    effective_run_kind = caller_scope if caller_scope == schemas.RunKind.DEMO else (run_kind or caller_scope)
    items = crud.get_reviews(db, run_kind=effective_run_kind)

    if status:
        items = [i for i in items if i.review.status == status]
    if notified is not None:
        if notified:
            items = [i for i in items if i.review.notified_at is not None]
        else:
            items = [i for i in items if i.review.notified_at is None]

    return items


@api_router.post("/reviews/{review_id}/notified", response_model=schemas.Review)
def review_notified(
    review_id: str,
    req: schemas.NotifiedRequest,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    caller_scope = _get_caller_scope(x_run_kind)
    c = crud.get_case_by_review_id(db, review_id)
    if not c:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    schema_case = crud.map_db_to_schema(c)
    if schema_case.run.kind == schemas.RunKind.EVAL and caller_scope != schemas.RunKind.EVAL:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    if schema_case.review and schema_case.review.review_id == review_id:
        if schema_case.review.notified_at is not None:
            return schema_case.review
        if schema_case.review.status != schemas.ReviewStatus.OPEN:
            raise HTTPException(status_code=409, detail=schemas.ErrorCode.REVIEW_ALREADY_CLOSED.value)
        if schema_case.run.run_id != req.run_id:
            raise HTTPException(status_code=409, detail=schemas.ErrorCode.STALE_RUN.value)

        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        schema_case.review.notified_at = now
        schema_case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=schema_case.run.run_id,
                at=now,
                type=schemas.HistoryEventType.REVIEW_NOTIFIED.value,
                actor=schemas.Actor(kind="SYSTEM"),
                summary="Review notification recorded"
            )
        )
        crud.update_case(db, c, schema_case)
        return schema_case.review

    raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)


@api_router.post("/reviews/{review_id}/decision", status_code=status.HTTP_202_ACCEPTED)
def submit_decision(
    review_id: str,
    req: schemas.DecisionRequest,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    caller_scope = _get_caller_scope(x_run_kind)
    c = crud.get_case_by_review_id(db, review_id)
    if not c:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    schema_case = crud.map_db_to_schema(c)
    if schema_case.run.kind == schemas.RunKind.EVAL and caller_scope != schemas.RunKind.EVAL:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    if not schema_case.review or schema_case.review.review_id != review_id:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    # Concurrency and stale-run checks
    case_dict = schema_case.model_dump(mode='json', by_alias=True)
    if schema_case.review.status != schemas.ReviewStatus.OPEN:
        raise HTTPException(
            status_code=409,
            detail={"code": schemas.ErrorCode.REVIEW_ALREADY_CLOSED.value, "message": "Review already closed", "current_case": case_dict}
        )
    if schema_case.run.run_id != req.run_id:
        raise HTTPException(
            status_code=409,
            detail={"code": schemas.ErrorCode.STALE_RUN.value, "message": "Stale run ID", "current_case": case_dict}
        )

    # Escape routes: NONE_OF_THESE for CHOICE, or "I can't tell" for VALUE_INPUT terminate in BLOCKED_EXTERNAL (Contract §5)
    is_escape = (
        (req.action == schemas.DecisionAction.SELECT_OPTION and req.option_id == "NONE_OF_THESE")
        or (req.user_message and req.user_message.strip().lower() in ("i can't tell", "i cant tell", "cannot tell"))
    )

    # Action validation (unless user is using an authorized escape route)
    if not is_escape:
        if req.action not in schema_case.review.allowed_actions:
            raise HTTPException(
                status_code=422,
                detail=schemas.ErrorCode.ACTION_NOT_ALLOWED.value
            )

        # Specific action checks
        if req.action == schemas.DecisionAction.SELECT_OPTION:
            valid_options = [opt.option_id for opt in schema_case.review.options] if schema_case.review.options else []
            if req.option_id not in valid_options:
                raise HTTPException(
                    status_code=422,
                    detail=schemas.ErrorCode.OPTION_NOT_FOUND.value
                )

        if req.action == schemas.DecisionAction.PROVIDE_VALUE:
            if req.value is None or str(req.value).strip() == "":
                raise HTTPException(
                    status_code=422,
                    detail=schemas.ErrorCode.INVALID_VALUE.value
                )

    # Override confirmation validation
    if req.override_confirmation:
        oc = req.override_confirmation
        if (
            oc.review_id != review_id
            or oc.run_id != schema_case.run.run_id
            or (req.field and oc.field != req.field)
            or (req.side and oc.side != req.side)
        ):
            raise HTTPException(
                status_code=422,
                detail=schemas.ErrorCode.INVALID_CONFIRMATION.value
            )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    schema_case.review.status = schemas.ReviewStatus.CLOSED
    schema_case.review.closed_at = now
    schema_case.review.close_reason = "DECISION_ACCEPTED"

    # Persist resolution
    schema_case.resolution = schemas.Resolution(
        review_id=review_id,
        run_id=schema_case.run.run_id,
        action=req.action,
        value_source=schemas.ValueSource.MANUAL_OVERRIDE if req.override_confirmation else schemas.ValueSource.DOCUMENT_CONFIRMED,
        actor_id=req.actor_id,
        channel=req.channel,
        user_message=req.user_message,
        resolved_at=now,
        final_status=schemas.MachineStatus.OK,
        final_defect_fields=[]
    )

    decision_details = {
        "action": req.action.value,
        "value": req.value,
        "option_id": req.option_id,
        "field": req.field.value if req.field else None,
        "side": req.side.value if req.side else None,
        "override_confirmation": req.override_confirmation.model_dump(mode="json") if req.override_confirmation else None
    }

    schema_case.history.append(
        schemas.HistoryEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            run_id=schema_case.run.run_id,
            at=now,
            type=schemas.HistoryEventType.DECISION_RECEIVED.value,
            actor=schemas.Actor(kind="HUMAN", id=req.actor_id),
            summary=f"Decision {req.action.value} received",
            details=decision_details
        )
    )

    # Escape routes: NONE_OF_THESE or "I can't tell" terminate in BLOCKED_EXTERNAL (Contract §5)
    is_escape = (
        (req.action == schemas.DecisionAction.SELECT_OPTION and req.option_id == "NONE_OF_THESE")
        or (req.user_message and req.user_message.strip().lower() in ("i can't tell", "i cant tell", "cannot tell"))
    )

    # Review budget check: at most 2 accepted decisions per field per run
    target_field = req.field or (schema_case.review.field if schema_case.review else None)
    prior_field_decisions = 0
    if target_field:
        for ev in schema_case.history:
            if ev.type == schemas.HistoryEventType.DECISION_APPLIED.value and ev.run_id == schema_case.run.run_id:
                if ev.details and ev.details.get("field") == target_field.value:
                    prior_field_decisions += 1

    budget_exhausted = (prior_field_decisions >= 2)

    # ACKNOWLEDGE, escape route, or exhausted review budget transitions case to BLOCKED_EXTERNAL
    if req.action == schemas.DecisionAction.ACKNOWLEDGE or is_escape or budget_exhausted:
        schema_case.workflow_status = schemas.WorkflowStatus.BLOCKED_EXTERNAL
        schema_case.follow_up = schemas.FollowUp.AWAIT_EXTERNAL
        summary_msg = "Acknowledgment applied, workflow blocked external"
        if is_escape:
            summary_msg = "Review escape selected, workflow blocked external"
        elif budget_exhausted:
            summary_msg = f"Review budget exhausted for field {target_field}, workflow blocked external"

        schema_case.history.append(
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=schema_case.run.run_id,
                at=now,
                type=schemas.HistoryEventType.DECISION_APPLIED.value,
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary=summary_msg,
                details=decision_details
            )
        )
        return crud.update_case(db, c, schema_case)

    # PROVIDE_VALUE and SELECT_OPTION enqueue APPLY_DECISION
    schema_case.workflow_status = schemas.WorkflowStatus.PROCESSING
    crud.update_case_and_create_job(db, c, schema_case, "APPLY_DECISION")
    return schema_case


@api_router.get("/documents/{document_id}/content")
def get_document_content(
    document_id: str,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    caller_scope = _get_caller_scope(x_run_kind)
    cases = crud.get_cases(db, skip=0, limit=10_000)
    matched_doc = None
    matched_case = None

    for c in cases:
        schema_case = crud.map_db_to_schema(c)
        for doc in schema_case.documents:
            if doc.document_id == document_id:
                matched_doc = doc
                matched_case = schema_case
                break
        if matched_doc:
            break

    if not matched_doc:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    # AC-07: Public request for non-demo or non-demo-safe content returns 404
    if matched_case.run.kind == schemas.RunKind.EVAL and caller_scope != schemas.RunKind.EVAL:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)
    if not matched_doc.demo_safe and caller_scope == schemas.RunKind.DEMO:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    from pathlib import Path
    safe_filename = Path(matched_doc.filename).name
    bundle_att = Path(__file__).resolve().parent.parent / "resources" / "sdoc-hackathon-bundle" / "attachments" / safe_filename
    if bundle_att.exists():
        content_bytes = bundle_att.read_bytes()
    else:
        content_bytes = f"Document content for {matched_doc.filename} ({matched_doc.document_id})".encode("utf-8")

    return Response(
        content=content_bytes,
        media_type=matched_doc.media_type or "application/octet-stream",
        headers={
            "Content-Disposition": f'inline; filename="{safe_filename}"'
        }
    )


@api_router.get("/stats", response_model=schemas.Stats)
def get_stats(
    run_kind: schemas.RunKind = schemas.RunKind.DEMO,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    caller_scope = _get_caller_scope(x_run_kind)
    # If a public user requests EVAL stats, restrict to DEMO
    effective_run_kind = caller_scope if caller_scope == schemas.RunKind.DEMO else run_kind

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    cases = crud.get_cases(db, skip=0, limit=10_000)

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
        if case.run.kind != effective_run_kind:
            continue
        total_filtered += 1

        cat = case.email.category.value if case.email.category else None
        if cat:
            by_category[cat] = by_category.get(cat, 0) + 1
        else:
            unclassified += 1

        wf = case.workflow_status.value
        by_workflow[wf] = by_workflow.get(wf, 0) + 1

        if (
            case.workflow_status in (schemas.WorkflowStatus.AWAITING_HUMAN, schemas.WorkflowStatus.BLOCKED_EXTERNAL)
            and case.review
            and case.review.status == schemas.ReviewStatus.OPEN
        ):
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

        # Auto-completed: COMPLETED runs with zero reviews created throughout the run
        if case.workflow_status == schemas.WorkflowStatus.COMPLETED:
            had_review = any(
                ev.type == schemas.HistoryEventType.REVIEW_CREATED.value and ev.run_id == case.run.run_id
                for ev in case.history
            )
            if not had_review:
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
        run_kind=effective_run_kind,
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
