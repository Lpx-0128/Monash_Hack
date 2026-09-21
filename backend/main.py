from contextlib import asynccontextmanager
import json
import os
from fastapi import (
    FastAPI, Depends, HTTPException, status, Response, Request, Header, APIRouter,
    Form, File, UploadFile
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from sqlalchemy.orm import Session
from sqlalchemy import text
from typing import List, Optional, Any
from datetime import datetime, timezone
from pathlib import Path
import uuid
from . import schemas, models, crud, worker
from .inbox import GmailConfig, GmailConnector
from .inbox.gmail import _sanitize_filename
from .intelligence import ingestion, wire
from .intelligence.recomputation import (
    DecisionProposal,
    OverrideConfirmation,
    ProposalRejected,
    validate_human_proposal,
)
from .intelligence.types import SourceDataIssue
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

# Enable CORS for dashboard frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    limit: int = 1000,
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

    try:
        case = crud.create_case_with_job(db, req.email_id, run_kind=run_kind,
                                         public_caller=(run_kind == schemas.RunKind.DEMO))
    except SourceDataIssue as exc:
        # An unregistered email id never produces a fabricated source.
        raise HTTPException(
            status_code=404,
            detail={"code": schemas.ErrorCode.NOT_FOUND.value, "message": str(exc)},
        )
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
    skipped: list[str] = []   # ids with no registered source

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
            try:
                crud.create_case_with_job(db, email_id, run_kind=run_kind,
                                          public_caller=(run_kind == schemas.RunKind.DEMO))
            except SourceDataIssue:
                skipped.append(email_id)
                continue
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

    # Pin the new run to the identities its inputs and configuration actually
    # have. A placeholder here would survive into the persisted run and make the
    # run unreproducible.
    try:
        fresh = crud.load_input_snapshot(schema_case.email.email_id, caller_scope)
        input_version = fresh.input_version
        demo_safe = (caller_scope == schemas.RunKind.DEMO and fresh.demo_safe)
    except SourceDataIssue as exc:
        raise HTTPException(
            status_code=404,
            detail={"code": schemas.ErrorCode.NOT_FOUND.value, "message": str(exc)},
        )

    schema_case.run = schemas.Run(
        run_id=new_run_id,
        kind=caller_scope,
        started_at=now,
        input_version=input_version,
        config_version=crud.intelligence_config().config_identity(),
        demo_safe=demo_safe,
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
    """Accept one human decision durably, then return the case in PROCESSING.

    Every accepted action — including acknowledgment — returns the same durable
    202 envelope. ``resolution`` keeps the previously applied result, or null:
    the newly accepted decision is a pending fact, not a finished one.
    """
    caller_scope = _get_caller_scope(x_run_kind)
    c = crud.get_case_by_review_id(db, review_id)
    if not c:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    schema_case = crud.map_db_to_schema(c)
    if schema_case.run.kind == schemas.RunKind.EVAL and caller_scope != schemas.RunKind.EVAL:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    if not schema_case.review or schema_case.review.review_id != review_id:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)
    if req.review_id != review_id:
        raise HTTPException(
            status_code=422,
            detail={"code": schemas.ErrorCode.ACTION_NOT_ALLOWED.value,
                    "message": "the body review_id must match the path"},
        )

    case_dict = schema_case.model_dump(mode="json", by_alias=True)
    # A closed review yields REVIEW_ALREADY_CLOSED before any stale-run detail.
    if schema_case.review.status != schemas.ReviewStatus.OPEN:
        raise HTTPException(
            status_code=409,
            detail={"code": schemas.ErrorCode.REVIEW_ALREADY_CLOSED.value,
                    "message": "Review already closed", "current_case": case_dict},
        )
    if schema_case.run.run_id != req.run_id:
        raise HTTPException(
            status_code=409,
            detail={"code": schemas.ErrorCode.STALE_RUN.value,
                    "message": "Stale run ID", "current_case": case_dict},
        )

    requirement = wire.requirement_from_review(schema_case.review)
    proposal = DecisionProposal(
        review_id=review_id,
        run_id=req.run_id,
        action=req.action.value,
        actor_id=req.actor_id,
        channel=req.channel.value,
        field=req.field.value if req.field else None,
        side=req.side.value if req.side else None,
        value=req.value,
        option_id=req.option_id,
        user_message=req.user_message,
        override_confirmation=(
            OverrideConfirmation(
                review_id=req.override_confirmation.review_id,
                run_id=req.override_confirmation.run_id,
                field=req.override_confirmation.field.value,
                side=req.override_confirmation.side.value,
                proposed_value=req.override_confirmation.proposed_value,
                confirmed=req.override_confirmation.confirmed,
            )
            if req.override_confirmation else None
        ),
    )

    context = worker._build_context(schema_case)
    try:
        state = _decision_state(schema_case, db)
        decision = validate_human_proposal(proposal, requirement, state, context)
    except ProposalRejected as exc:
        # A rejected proposal closes nothing, enqueues nothing and consumes no
        # accepted-decision budget. The review stays OPEN.
        raise HTTPException(status_code=422,
                            detail={"code": exc.code, "message": exc.message})
    except worker.RunStateUnavailable as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": schemas.ErrorCode.STALE_RUN.value, "message": str(exc)},
        )
    except worker.RunIdentityChanged as exc:
        # The run can no longer be reasoned about; reprocessing is the remedy.
        raise HTTPException(
            status_code=409,
            detail={"code": schemas.ErrorCode.STALE_RUN.value, "message": str(exc)},
        )
    except SourceDataIssue as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": schemas.ErrorCode.INVALID_VALUE.value, "message": str(exc)},
        )

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    schema_case.review.status = schemas.ReviewStatus.CLOSED
    schema_case.review.closed_at = now
    schema_case.review.close_reason = "DECISION_ACCEPTED"

    schema_case.history.append(
        schemas.HistoryEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            run_id=schema_case.run.run_id,
            at=now,
            type=schemas.HistoryEventType.DECISION_RECEIVED.value,
            actor=schemas.Actor(kind="HUMAN", id=req.actor_id),
            summary=f"Decision {req.action.value} accepted",
            details={"decision_id": decision.decision_id, "action": decision.action,
                     "field": decision.target_field, "side": decision.target_side,
                     "target_role": decision.target_role, "escape": decision.escape},
        )
    )

    # Acceptance is durable but not applied: PROCESSING, previous resolution kept.
    schema_case.workflow_status = schemas.WorkflowStatus.PROCESSING
    schema_case.updated_at = now
    crud.update_case_with_decision(db, c, schema_case, decision, requirement, now)
    return schema_case


def _decision_state(schema_case: schemas.Case, db: Session):
    """The working state a proposal is validated against.

    This is the same loader the worker applies decisions through, so validation
    and application always see one state: the run's immutable automated analysis
    plus exactly the decisions already durably applied to it. Validating against
    a freshly rerun analysis instead would ignore an earlier accepted document
    choice and reject a value the chosen document genuinely supports.
    """
    state, _context, _snapshot, _restored, _applied = worker.load_working_state(
        db, schema_case, schema_case.run.run_id
    )
    return state


@api_router.get("/documents/{document_id}/content")
def get_document_content(
    document_id: str,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db)
):
    """Stream the exact registered bytes for an authorized document.

    Placeholder content is never synthesized and the document is never resolved
    by filename: the identity must belong to a case in the caller's scope, and
    the bytes must still hash to what the run ingested.
    """
    caller_scope = _get_caller_scope(x_run_kind)

    matched_doc = None
    matched_case = None
    for c in crud.get_cases(db, skip=0, limit=10_000):
        schema_case = crud.map_db_to_schema(c)
        for doc in schema_case.documents:
            if doc.document_id == document_id:
                matched_doc, matched_case = doc, schema_case
                break
        if matched_doc:
            break

    if not matched_doc:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    # Public access needs DEMO scope *and* explicit demo-safe authorization.
    if matched_case.run.kind == schemas.RunKind.EVAL and caller_scope != schemas.RunKind.EVAL:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)
    if not matched_doc.demo_safe and caller_scope == schemas.RunKind.DEMO:
        raise HTTPException(status_code=404, detail=schemas.ErrorCode.NOT_FOUND.value)

    try:
        snapshot = crud.load_input_snapshot(matched_case.email.email_id, matched_case.run.kind)
        content_bytes = ingestion.read_source_bytes(
            snapshot, document_id, registries=crud.intelligence_registries()
        )
    except SourceDataIssue as exc:
        # Fail honestly rather than inventing bytes.
        raise HTTPException(
            status_code=404,
            detail={"code": schemas.ErrorCode.NOT_FOUND.value, "message": str(exc)},
        )
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": schemas.ErrorCode.INTERNAL.value,
                    "message": f"the document store is unavailable: {exc}"},
        )

    safe_filename = Path(matched_doc.filename).name
    return Response(
        content=content_bytes,
        media_type=matched_doc.media_type or "application/octet-stream",
        headers={"Content-Disposition": f'inline; filename="{safe_filename}"'},
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


# ---------------------------------------------------------------------------
# Live Inbox & Mock Email Ingestion Endpoints
# ---------------------------------------------------------------------------

@api_router.post("/inbox/compose", response_model=schemas.Case, status_code=status.HTTP_202_ACCEPTED)
async def compose_mock_email(
    from_address: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    files: List[UploadFile] = File(default=[]),
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db),
):
    """Compose a mock incoming email with arbitrary attachments for live verification."""
    run_kind = _get_caller_scope(x_run_kind)

    # Validate inputs
    from_clean = from_address.strip()
    subject_clean = subject.strip()
    body_clean = body.strip()

    if not from_clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": schemas.ErrorCode.INVALID_VALUE.value, "message": "from_address is required"},
        )
    if not subject_clean:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": schemas.ErrorCode.INVALID_VALUE.value, "message": "subject is required"},
        )

    # Resolve demo storage root
    demo_env = os.environ.get("INTELLIGENCE_DEMO_SOURCE_ROOT")
    if demo_env:
        demo_root = Path(demo_env).resolve()
    else:
        repo_root = Path(__file__).resolve().parent.parent
        demo_root = repo_root / "resources" / "demo-fixtures"

    inbox_dir = demo_root / "inbox"
    attachments_dir = demo_root / "attachments"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    attachments_dir.mkdir(parents=True, exist_ok=True)

    # Generate unique ID
    now_dt = datetime.now(timezone.utc)
    stamp = now_dt.strftime("%Y%m%d_%H%M%S")
    short_uuid = uuid.uuid4().hex[:6]
    email_id = f"email_custom_{stamp}_{short_uuid}"

    saved_attachments = []
    for idx, uploaded in enumerate(files):
        if not uploaded.filename:
            continue
        content = await uploaded.read()
        safe_name = _sanitize_filename(uploaded.filename)
        filename_on_disk = f"{email_id}_{idx}_{safe_name}"
        file_path = attachments_dir / filename_on_disk
        file_path.write_bytes(content)
        saved_attachments.append(f"attachments/{filename_on_disk}")

    # Write email JSON
    email_record = {
        "email_id": email_id,
        "from": from_clean,
        "subject": subject_clean,
        "body": body_clean,
        "received_at": now_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "attachments": saved_attachments,
    }

    json_path = inbox_dir / f"{email_id}.json"
    json_path.write_text(json.dumps(email_record, indent=2, ensure_ascii=False), encoding="utf-8")

    # Ingest case and enqueue job
    case = crud.create_case_with_job(
        db,
        email_id=email_id,
        run_kind=run_kind,
        public_caller=(run_kind == schemas.RunKind.DEMO),
    )
    return case


@api_router.post("/inbox/gmail/sync", response_model=schemas.GmailSyncResponse)
def sync_gmail_inbox(
    req: schemas.GmailSyncRequest = None,
    x_run_kind: Optional[str] = Header(None, alias="X-Run-Kind"),
    db: Session = Depends(get_db),
):
    """Trigger an on-demand sync from Gmail over IMAP SSL."""
    run_kind = _get_caller_scope(x_run_kind)
    req = req or schemas.GmailSyncRequest()

    config = GmailConfig.from_env()
    if req.username and req.app_password:
        config = GmailConfig(
            username=req.username,
            app_password=req.app_password,
            imap_server=config.imap_server,
            imap_port=config.imap_port,
            folder=config.folder,
            mark_as_read=config.mark_as_read,
        )

    if not config.is_configured:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": schemas.ErrorCode.INVALID_VALUE.value,
                "message": "Gmail credentials not configured. Provide username and app_password in request or environment variables.",
            },
        )

    connector = GmailConnector(config=config)
    try:
        result = connector.sync(db, limit=req.limit, run_kind=run_kind)
        return schemas.GmailSyncResponse(
            status="OK",
            fetched=result["fetched"],
            created_cases=result["created_cases"],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail={
                "code": schemas.ErrorCode.INTERNAL.value,
                "message": f"Gmail IMAP synchronization failed: {exc}",
            },
        )


@api_router.get("/inbox/gmail/status", response_model=schemas.GmailStatusResponse)
def get_gmail_status():
    """Check Gmail IMAP connectivity and count unread messages."""
    connector = GmailConnector()
    res = connector.test_connection()
    return schemas.GmailStatusResponse(
        configured=res.get("configured", False),
        connected=res.get("connected", False),
        folder=res.get("folder"),
        unseen_count=res.get("unseen_count"),
        error=res.get("error"),
    )


# Mount the versioned router
app.include_router(api_router)

# ---------------------------------------------------------------------------
# Frontend SPA Static Files (Render / Production deployment)
# ---------------------------------------------------------------------------
dist_dir = Path(__file__).resolve().parent.parent / "dist"
if dist_dir.exists() and (dist_dir / "index.html").exists():
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse

    if (dist_dir / "assets").exists():
        app.mount("/assets", StaticFiles(directory=str(dist_dir / "assets")), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        if full_path.startswith("api/") or full_path.startswith("health"):
            raise HTTPException(status_code=404, detail="Not found")
        file_path = dist_dir / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        return FileResponse(dist_dir / "index.html")

