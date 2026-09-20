from sqlalchemy.orm import Session
from . import models, schemas
import json
from datetime import datetime, timezone
import uuid

def get_case(db: Session, case_id: str):
    return db.query(models.CaseModel).filter(models.CaseModel.case_id == case_id).first()

def get_cases(db: Session, skip: int = 0, limit: int = 100):
    return db.query(models.CaseModel).offset(skip).limit(limit).all()

def get_reviews(db: Session, run_kind: schemas.RunKind = None):
    # For now, just load all cases and filter in Python
    cases = db.query(models.CaseModel).all()
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

def create_initial_case(db: Session, email_id: str) -> schemas.Case:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    run_id = f"run_{uuid.uuid4().hex[:8]}"
    
    case = schemas.Case(
        schema_version="2.1.1",
        case_id=email_id,
        run=schemas.Run(
            run_id=run_id,
            kind=schemas.RunKind.DEMO,
            started_at=now,
            input_version="v1",
            config_version="v1",
            demo_safe=True
        ),
        email=schemas.EmailInfo(**{
            "email_id": email_id,
            "from": "unknown@example.com",
            "subject": "Pending classification",
            "received_at": None,
            "category": None,
            "classified_by": None,
            "classification_reason": None
        }),
        documents=[],
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
                type="CASE_CREATED",
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
    return create_case(db, case)

def map_db_to_schema(db_case: models.CaseModel) -> schemas.Case:
    data = {
        "case_id": db_case.case_id,
        "schema_version": db_case.schema_version,
        "workflow_status": db_case.workflow_status,
        "machine_assessment": db_case.machine_assessment,
        "resolution": db_case.resolution,
        "follow_up": db_case.follow_up,
        "created_at": db_case.created_at,
        "updated_at": db_case.updated_at,
        "completed_at": db_case.completed_at,
        
        "run": db_case.run,
        "email": db_case.email,
        "documents": db_case.documents,
        "fields": db_case.fields_data,
        "review": json.loads(json.dumps(db_case.review)) if db_case.review else None,
        "failure": json.loads(json.dumps(db_case.failure)) if db_case.failure else None,
        "history": json.loads(json.dumps(db_case.history)) if db_case.history else [],
        "metrics": db_case.metrics,
    }
    return schemas.Case(**data)

def map_case_to_summary(case: schemas.Case) -> schemas.CaseSummary:
    machine_status = case.machine_assessment.status if case.machine_assessment else None
    review_reason = case.machine_assessment.review_reason if case.machine_assessment else None
    final_status = case.resolution.final_status if case.resolution else None
    
    return schemas.CaseSummary(**{
        "case_id": case.case_id,
        "run_id": case.run.run_id,
        "from": case.email.from_address,
        "subject": case.email.subject,
        "category": case.email.category,
        "workflow_status": case.workflow_status,
        "machine_status": machine_status,
        "review_reason": review_reason,
        "final_status": final_status,
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
            attempts = list(job.attempts)
            attempts.append({"at": now, "error": error})
            job.attempts = attempts
        db.commit()
        db.refresh(job)
    return job
