from sqlalchemy.orm import Session
from sqlalchemy import text as sa_text, func
from . import models, schemas
from .intelligence import config as config_module
from .intelligence import ingestion
from .intelligence.types import SourceDataIssue
import json
import copy
from datetime import datetime, timezone
import uuid


def get_case(db: Session, case_id: str):
    return db.query(models.CaseModel).filter(models.CaseModel.case_id == case_id).first()


def get_cases(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.CaseModel).offset(skip).limit(limit).all()


def get_case_by_review_id(db: Session, review_id: str):
    """Find the case that contains the specified review_id."""
    try:
        case = db.query(models.CaseModel).filter(
            func.json_extract(models.CaseModel.review, '$.review_id') == review_id
        ).first()
        if case:
            return case
    except Exception:
        pass

    cases_with_reviews = db.query(models.CaseModel).filter(models.CaseModel.review.isnot(None)).all()
    for c in cases_with_reviews:
        if c.review and isinstance(c.review, dict) and c.review.get("review_id") == review_id:
            return c
    return None


def get_reviews(db: Session, run_kind: schemas.RunKind = None):
    """Load open reviews efficiently."""
    cases = db.query(models.CaseModel).filter(models.CaseModel.review.isnot(None)).all()
    results = []
    for c in cases:
        schema_case = map_db_to_schema(c)
        if schema_case.review and schema_case.review.status == schemas.ReviewStatus.OPEN:
            if run_kind and schema_case.run.kind != run_kind:
                continue
            results.append(schemas.ReviewListItem(
                review=schema_case.review,
                case=map_case_to_summary(schema_case)
            ))
    return results


def create_case(db: Session, case: schemas.Case):
    case_data = case.model_dump(mode='json', by_alias=True)
    
    db_case = models.CaseModel(
        case_id=case_data["case_id"],
        schema_version=case_data.get("schema_version", "2.1.1"),
        workflow_status=case_data["workflow_status"],
        machine_assessment=case_data.get("machine_assessment"),
        resolution=case_data.get("resolution"),
        follow_up=case_data.get("follow_up"),
        created_at=case_data["created_at"],
        updated_at=case_data["updated_at"],
        completed_at=case_data.get("completed_at"),
        
        run=case_data["run"],
        email=case_data["email"],
        documents=case_data.get("documents", []),
        fields_data=case_data.get("fields", []),
        review=case_data.get("review"),
        failure=case_data.get("failure"),
        history=case_data.get("history", []),
        metrics=case_data["metrics"],
    )
    db.add(db_case)
    db.commit()
    db.refresh(db_case)
    return map_db_to_schema(db_case)


def update_case(db: Session, db_case: models.CaseModel, case: schemas.Case):
    case_data = case.model_dump(mode='json', by_alias=True)
    
    db_case.workflow_status = case_data["workflow_status"]
    db_case.machine_assessment = case_data.get("machine_assessment")
    db_case.resolution = case_data.get("resolution")
    db_case.follow_up = case_data.get("follow_up")
    db_case.updated_at = case_data["updated_at"]
    db_case.completed_at = case_data.get("completed_at")
    
    db_case.run = case_data["run"]
    db_case.email = case_data["email"]
    db_case.documents = case_data.get("documents", [])
    db_case.fields_data = case_data.get("fields", [])
    db_case.review = case_data.get("review")
    db_case.failure = case_data.get("failure")
    db_case.history = case_data.get("history", [])
    db_case.metrics = case_data["metrics"]
    
    db.commit()
    db.refresh(db_case)
    return map_db_to_schema(db_case)


# --- Person A source adapter ------------------------------------------------
# Sources come from a configured registry. Nothing here invents a hash, a
# document, a role or a receipt time, and participant bytes are never marked
# demo-safe.

_INTELLIGENCE_CONFIG = None
_INTELLIGENCE_REGISTRIES = None


def intelligence_config():
    """The validated Person A configuration for this process."""
    global _INTELLIGENCE_CONFIG
    if _INTELLIGENCE_CONFIG is None:
        _INTELLIGENCE_CONFIG = config_module.load_config()
    return _INTELLIGENCE_CONFIG


def intelligence_registries():
    """The configured participant and synthetic-demo source registries."""
    global _INTELLIGENCE_REGISTRIES
    if _INTELLIGENCE_REGISTRIES is None:
        _INTELLIGENCE_REGISTRIES = ingestion.build_registries(intelligence_config())
    return _INTELLIGENCE_REGISTRIES


def reset_intelligence_cache():
    """Drop the cached config and registries. Used by tests that repoint roots."""
    global _INTELLIGENCE_CONFIG, _INTELLIGENCE_REGISTRIES
    _INTELLIGENCE_CONFIG = None
    _INTELLIGENCE_REGISTRIES = None


def load_input_snapshot(email_id: str, run_kind: schemas.RunKind, *,
                        public_caller: bool = False) -> ingestion.InputSnapshot:
    """Map a registered source record into this run's immutable input snapshot.

    Raises ``SourceDataIssue`` for an email id that is not registered anywhere:
    an unknown id never produces a fabricated source. When
    ``INTELLIGENCE_ALLOW_PUBLIC_PARTICIPANT_INGEST`` is off, a public caller may
    ingest only synthetic demo fixtures; participant ingestion then needs the
    authenticated operator path Person B owns.
    """
    config = intelligence_config()
    if public_caller and not config.allow_public_participant_ingest:
        registry = ingestion.find_registry(email_id, intelligence_registries())
        if registry is not None and registry.kind == ingestion.PARTICIPANT:
            raise SourceDataIssue(
                f"{email_id!r} is a participant source and public ingestion is disabled"
            )
    return ingestion.ingest_case(
        email_id,
        namespace=run_kind.value,
        case_id=email_id,
        registries=intelligence_registries(),
        config=intelligence_config(),
    )


def snapshot_to_document_refs(snapshot: ingestion.InputSnapshot) -> list[schemas.DocumentRef]:
    """Contract DocumentRefs for a freshly ingested, not-yet-parsed input.

    Roles start UNKNOWN because only document content may assign them, and a
    missing file carries no content hash.
    """
    refs = []
    for source in snapshot.sources:
        if not source.present:
            continue
        refs.append(schemas.DocumentRef(
            document_id=source.document_id,
            role=schemas.DocumentRole.UNKNOWN,
            filename=source.filename,
            media_type=source.media_type,
            size_bytes=source.size_bytes,
            content_hash=source.content_hash or "",
            demo_safe=source.demo_safe,
            parse_status="NOT_PARSED",
        ))
    return refs


def create_case_with_job(db: Session, email_id: str,
                         run_kind: schemas.RunKind = schemas.RunKind.DEMO,
                         public_caller: bool = False) -> schemas.Case:
    """Create the initial case AND its first PROCESS_CASE job in one commit.

    Prevents the crash window where a case exists in PROCESSING but no job
    ever picks it up.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    job_id = f"job_{uuid.uuid4().hex[:8]}"

    snapshot = load_input_snapshot(email_id, run_kind, public_caller=public_caller)
    docs = snapshot_to_document_refs(snapshot)

    case_schema = schemas.Case(
        schema_version="2.1.1",
        case_id=email_id,
        run=schemas.Run(
            run_id=run_id,
            kind=run_kind,
            started_at=now,
            input_version=snapshot.input_version,
            config_version=intelligence_config().config_identity(),
            # A DEMO run is only demo-safe when every source in it is.
            demo_safe=(run_kind == schemas.RunKind.DEMO and snapshot.demo_safe)
        ),
        email=schemas.EmailInfo(**{
            "email_id": email_id,
            "from": snapshot.from_address,
            "subject": snapshot.subject,
            # Unknown receipt time stays explicitly null; it is never inferred.
            "received_at": snapshot.received_at,
            "category": None,
            "classified_by": None,
            "classification_reason": None
        }),
        documents=docs,
        workflow_status=schemas.WorkflowStatus.PROCESSING,
        machine_assessment=None,
        fields=[],
        review=None,
        resolution=None,
        follow_up=schemas.FollowUp.NONE,
        failure=None,
        history=[
            schemas.HistoryEvent(
                event_id=f"evt_{uuid.uuid4().hex[:8]}",
                run_id=run_id,
                at=now,
                type=schemas.HistoryEventType.CASE_CREATED.value,
                actor=schemas.Actor(kind="SYSTEM", id=None),
                summary="Case ingested and run enqueued"
            )
        ],
        metrics=schemas.Metrics(
            ai_calls=0,
            ai_assisted_fields=0,
            processing_ms=None,
            est_ai_cost_usd=None
        ),
        created_at=now,
        updated_at=now,
        completed_at=None
    )
    case_data = case_schema.model_dump(mode='json', by_alias=True)
    db_case = models.CaseModel(
        case_id=case_data["case_id"],
        schema_version=case_data.get("schema_version", "2.1.1"),
        workflow_status=case_data["workflow_status"],
        machine_assessment=case_data.get("machine_assessment"),
        resolution=case_data.get("resolution"),
        follow_up=case_data.get("follow_up"),
        created_at=case_data["created_at"],
        updated_at=case_data["updated_at"],
        completed_at=case_data.get("completed_at"),
        run=case_data["run"],
        email=case_data["email"],
        documents=case_data.get("documents", []),
        fields_data=case_data.get("fields", []),
        review=case_data.get("review"),
        failure=case_data.get("failure"),
        history=case_data.get("history", []),
        metrics=case_data["metrics"],
    )
    db_job = models.JobModel(
        job_id=job_id,
        case_id=email_id,
        run_id=run_id,
        action="PROCESS_CASE",
        status="PENDING",
        attempts=[],
        created_at=now,
        updated_at=now,
    )
    db.add(db_case)
    db.add(db_job)
    db.commit()  # single commit — both or neither
    db.refresh(db_case)
    return map_db_to_schema(db_case)


def update_case_and_create_job(db: Session, db_case: models.CaseModel, case: schemas.Case, action: str):
    """Update a case and insert a new job in one commit.

    Prevents the crash window where the review is already closed but no
    APPLY_DECISION job exists, leaving the case stuck in PROCESSING.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    case_data = case.model_dump(mode='json', by_alias=True)
    db_case.workflow_status = case_data["workflow_status"]
    db_case.machine_assessment = case_data.get("machine_assessment")
    db_case.resolution = case_data.get("resolution")
    db_case.follow_up = case_data.get("follow_up")
    db_case.updated_at = case_data["updated_at"]
    db_case.completed_at = case_data.get("completed_at")
    db_case.run = case_data["run"]
    db_case.email = case_data["email"]
    db_case.documents = case_data.get("documents", [])
    db_case.fields_data = case_data.get("fields", [])
    db_case.review = case_data.get("review")
    db_case.failure = case_data.get("failure")
    db_case.history = case_data.get("history", [])
    db_case.metrics = case_data["metrics"]
    db_job = models.JobModel(
        job_id=f"job_{uuid.uuid4().hex[:8]}",
        case_id=case.case_id,
        run_id=case.run.run_id,
        action=action,
        status="PENDING",
        attempts=[],
        created_at=now,
        updated_at=now,
    )
    db.add(db_job)
    db.commit()  # single commit — both or neither
    db.refresh(db_case)


def update_case_with_decision(db: Session, db_case: models.CaseModel, case: schemas.Case,
                             decision, requirement, now: str):
    """Persist the case, the accepted decision and its APPLY_DECISION job together.

    One commit, so a crash can never leave a closed review with no pending work,
    nor an accepted decision that no job will ever apply.
    """
    from .intelligence import wire

    case_data = case.model_dump(mode='json', by_alias=True)
    db_case.workflow_status = case_data["workflow_status"]
    db_case.machine_assessment = case_data.get("machine_assessment")
    db_case.resolution = case_data.get("resolution")
    db_case.follow_up = case_data.get("follow_up")
    db_case.updated_at = case_data["updated_at"]
    db_case.completed_at = case_data.get("completed_at")
    db_case.run = case_data["run"]
    db_case.email = case_data["email"]
    db_case.documents = case_data.get("documents", [])
    db_case.fields_data = case_data.get("fields", [])
    db_case.review = case_data.get("review")
    db_case.failure = case_data.get("failure")
    db_case.history = case_data.get("history", [])
    db_case.metrics = case_data["metrics"]

    job_id = f"job_{uuid.uuid4().hex[:8]}"
    sequence = (
        db.query(func.count(models.AcceptedDecisionModel.decision_id))
        .filter(models.AcceptedDecisionModel.case_id == case.case_id)
        .filter(models.AcceptedDecisionModel.run_id == case.run.run_id)
        .scalar() or 0
    )
    db.add(models.AcceptedDecisionModel(
        decision_id=decision.decision_id,
        case_id=case.case_id,
        run_id=case.run.run_id,
        review_id=decision.review_id,
        job_id=job_id,
        sequence=sequence,
        payload=wire.decision_to_json(decision),
        review_requirement=wire.review_requirement_to_json(requirement),
        created_at=now,
        applied_at=None,
    ))
    db.add(models.JobModel(
        job_id=job_id,
        case_id=case.case_id,
        run_id=case.run.run_id,
        action="APPLY_DECISION",
        status="PENDING",
        attempts=[],
        created_at=now,
        updated_at=now,
    ))
    db.commit()   # case + decision + job, or none of them
    db.refresh(db_case)
    return map_db_to_schema(db_case)


def reprocess_case_atomic(db: Session, db_case: models.CaseModel, schema_case: schemas.Case) -> schemas.Case:
    """Supersede stale jobs, rewrite the case, and insert the new PROCESS_CASE job — all in one commit.

    Prevents the crash window where the case is rewritten to a new run but no
    job ever picks it up.
    """
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    new_job_id = f"job_{uuid.uuid4().hex[:8]}"

    # Step 1: supersede any PENDING or RUNNING jobs for this case
    db.execute(
        sa_text(
            "UPDATE jobs SET status='SUPERSEDED', updated_at=:now "
            "WHERE case_id=:case_id AND status IN ('PENDING','RUNNING')"
        ),
        {"now": now, "case_id": db_case.case_id}
    )

    # Step 1b: unapplied decisions from the superseded run must never be applied
    db.execute(
        sa_text(
            "DELETE FROM accepted_decisions "
            "WHERE case_id=:case_id AND applied_at IS NULL"
        ),
        {"case_id": db_case.case_id}
    )

    # Step 2: apply case mutations
    case_data = schema_case.model_dump(mode='json', by_alias=True)
    db_case.workflow_status = case_data["workflow_status"]
    db_case.machine_assessment = None
    db_case.resolution = None
    db_case.follow_up = schemas.FollowUp.NONE.value
    db_case.updated_at = case_data["updated_at"]
    db_case.completed_at = None
    db_case.run = case_data["run"]
    db_case.email = case_data["email"]
    db_case.documents = case_data.get("documents", [])
    db_case.fields_data = []  # Clear fields for fresh run
    db_case.review = None
    db_case.failure = None
    db_case.history = case_data.get("history", [])
    db_case.metrics = case_data["metrics"]

    # Step 3: insert the new PROCESS_CASE job
    db_job = models.JobModel(
        job_id=new_job_id,
        case_id=db_case.case_id,
        run_id=schema_case.run.run_id,
        action="PROCESS_CASE",
        status="PENDING",
        attempts=[],
        created_at=now,
        updated_at=now,
    )
    db.add(db_job)

    db.commit()  # single commit — all three or none
    db.refresh(db_case)
    return map_db_to_schema(db_case)


def map_db_to_schema(db_case: models.CaseModel) -> schemas.Case:
    data = {
        "case_id": db_case.case_id,
        "schema_version": db_case.schema_version,
        "workflow_status": db_case.workflow_status,
        "machine_assessment": copy.deepcopy(db_case.machine_assessment),
        "resolution": copy.deepcopy(db_case.resolution),
        "follow_up": db_case.follow_up,
        "created_at": db_case.created_at,
        "updated_at": db_case.updated_at,
        "completed_at": db_case.completed_at,
        "run": (
            {
                "run_id": db_case.run.get("run_id", "run_default"),
                "kind": db_case.run.get("kind", "DEMO"),
                "started_at": db_case.run.get("started_at", db_case.created_at),
                "input_version": db_case.run.get("input_version", "v1"),
                "config_version": db_case.run.get("config_version", "v1"),
                "demo_safe": db_case.run.get("demo_safe", True),
            }
            if isinstance(db_case.run, dict)
            else db_case.run
        ),
        "email": copy.deepcopy(db_case.email),
        "documents": copy.deepcopy(db_case.documents) if db_case.documents else [],
        "fields": copy.deepcopy(db_case.fields_data) if db_case.fields_data else [],
        "review": copy.deepcopy(db_case.review),
        "failure": copy.deepcopy(db_case.failure),
        "history": copy.deepcopy(db_case.history) if db_case.history else [],
        "metrics": copy.deepcopy(db_case.metrics),
    }
    return schemas.Case(**data)


def map_case_to_summary(case: schemas.Case) -> schemas.CaseSummary:
    machine_status = case.machine_assessment.status if case.machine_assessment else None
    review_reason = case.machine_assessment.review_reason if case.machine_assessment else None
    effective_status = (
        case.resolution.final_status
        if case.resolution
        else (case.machine_assessment.status if case.machine_assessment else None)
    )
    
    return schemas.CaseSummary(**{
        "case_id": case.case_id,
        "run_id": case.run.run_id,
        "from": case.email.from_address,
        "subject": case.email.subject,
        "category": case.email.category,
        "workflow_status": case.workflow_status,
        "machine_status": machine_status,
        "review_reason": review_reason,
        "final_status": effective_status,
        "mismatch_count": len([f for f in case.fields if f.result == schemas.FieldResult.MISMATCH]),
        "has_open_review": (case.review is not None and case.review.status == schemas.ReviewStatus.OPEN),
        "run_kind": case.run.kind,
        "updated_at": case.updated_at
    })


def create_job(db: Session, case_id: str, run_id: str, action: str):
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    job = models.JobModel(
        job_id=f"job_{uuid.uuid4().hex[:8]}",
        case_id=case_id,
        run_id=run_id,
        action=action,
        status="PENDING",
        attempts=[],
        created_at=now,
        updated_at=now
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def get_job(db: Session, job_id: str):
    return db.query(models.JobModel).filter(models.JobModel.job_id == job_id).first()


def get_pending_jobs(db: Session):
    return db.query(models.JobModel).filter(models.JobModel.status == "PENDING").all()


def update_job_status(db: Session, job_id: str, status: str, error: str = None):
    job = get_job(db, job_id)
    if job:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        job.status = status
        job.updated_at = now
        if error:
            attempts = list(job.attempts) if job.attempts else []
            attempts.append({"at": now, "error": error})
            job.attempts = attempts
        db.commit()
        db.refresh(job)
    return job


def clear_inbox_cases(db: Session) -> int:
    """Delete all dynamically synced Gmail and mock composer cases and associated jobs."""
    cases_to_delete = (
        db.query(models.CaseModel)
        .filter(
            (models.CaseModel.case_id.like("case_email_gmail_%"))
            | (models.CaseModel.case_id.like("case_email_custom_%"))
        )
        .all()
    )
    count = len(cases_to_delete)
    for c in cases_to_delete:
        db.delete(c)
    db.commit()
    return count


def clear_all_cases(db: Session) -> int:
    """Delete every case and associated job from the database."""
    all_cases = db.query(models.CaseModel).all()
    count = len(all_cases)
    for c in all_cases:
        db.delete(c)
    db.commit()
    return count


