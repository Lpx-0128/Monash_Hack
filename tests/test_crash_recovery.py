import pytest
import uuid
from datetime import datetime, timezone
from sqlalchemy import text
from backend import models, crud, schemas, database, worker_loop, worker


def test_recover_stale_running_jobs():
    db = database.SessionLocal()
    try:
        case_id = f"crashed_case_{uuid.uuid4().hex[:6]}"
        case = crud.create_case_with_job(db, case_id)
        
        # Set the job to RUNNING to simulate an abandoned job from a crash
        job = db.query(models.JobModel).filter_by(case_id=case_id).first()
        job.status = "RUNNING"
        db.commit()

        # Run recovery
        worker_loop._recover_stale_running_jobs(db)

        recovered_job = crud.get_job(db, job.job_id)
        assert recovered_job.status == "PENDING"
    finally:
        db.close()


def test_job_retry_and_permanent_failure():
    db = database.SessionLocal()
    try:
        case_id = f"failing_case_{uuid.uuid4().hex[:6]}"
        case = crud.create_case_with_job(db, case_id)
        job = db.query(models.JobModel).filter_by(case_id=case_id).first()

        # Attempt 1: should retry (status becomes PENDING)
        worker_loop._handle_job_failure(db, job, "Temporary network blip")
        db.refresh(job)
        assert job.status == "PENDING"

        # Attempt 2: should permanently fail (status becomes FAILED)
        worker_loop._handle_job_failure(db, job, "Permanent disk failure")
        db.refresh(job)
        assert job.status == "FAILED"

        # Verify case failure record
        db_case = crud.get_case(db, case_id)
        schema_case = crud.map_db_to_schema(db_case)
        assert schema_case.workflow_status == schemas.WorkflowStatus.FAILED
        assert schema_case.failure is not None
        assert schema_case.failure.attempts == 2

        # Verify PROCESSING_FAILED event
        event_types = [ev.type for ev in schema_case.history]
        assert "PROCESSING_FAILED" in event_types
    finally:
        db.close()


def test_stale_job_run_guard():
    db = database.SessionLocal()
    try:
        case_id = f"stale_guard_{uuid.uuid4().hex[:6]}"
        case = crud.create_case_with_job(db, case_id)

        # Worker is called with an old run_id (simulate race after reprocess)
        old_run_id = "run_ancient_123"
        assert worker._stale_run(db, case_id, old_run_id) is True
        assert worker._stale_run(db, case_id, case.run.run_id) is False
    finally:
        db.close()
