"""Durable work: recovery, retry and stale-run guards."""

import pytest

from backend import crud, database, models, schemas, worker, worker_loop
from tests.conftest import DEMO_MATCH, DEMO_MISSING_WEIGHT


@pytest.fixture
def db():
    session = database.SessionLocal()
    try:
        yield session
    finally:
        session.close()


def test_recover_stale_running_jobs(db):
    """A job left RUNNING by a crashed process is returned to the queue."""
    case = crud.create_case_with_job(db, DEMO_MATCH)
    job = db.query(models.JobModel).filter_by(case_id=DEMO_MATCH).first()
    job.status = "RUNNING"
    db.commit()

    worker_loop._recover_stale_running_jobs(db)
    assert crud.get_job(db, job.job_id).status == "PENDING"


def test_job_retry_then_permanent_failure(db):
    """One retry, then FAILED with a contract-shaped failure record."""
    case = crud.create_case_with_job(db, DEMO_MISSING_WEIGHT)
    job = db.query(models.JobModel).filter_by(case_id=DEMO_MISSING_WEIGHT).first()

    worker_loop._handle_job_failure(db, job, "Temporary network blip")
    db.refresh(job)
    assert job.status == "PENDING"

    worker_loop._handle_job_failure(db, job, "Permanent disk failure")
    db.refresh(job)
    assert job.status == "FAILED"

    schema_case = crud.map_db_to_schema(crud.get_case(db, DEMO_MISSING_WEIGHT))
    assert schema_case.workflow_status == schemas.WorkflowStatus.FAILED
    assert schema_case.failure is not None
    assert schema_case.failure.attempts == 2
    assert schema_case.failure.step
    assert schema_case.failure.message
    assert "PROCESSING_FAILED" in [event.type for event in schema_case.history]


def test_stale_job_run_guard(db):
    case = crud.create_case_with_job(db, DEMO_MATCH)
    assert worker._stale_run(db, DEMO_MATCH, "run_ancient_123") is True
    assert worker._stale_run(db, DEMO_MATCH, case.run.run_id) is False


def test_a_superseded_worker_cannot_write_into_a_newer_run(db):
    """The guard and the mutation share one transaction, so the race is closed."""
    case = crud.create_case_with_job(db, DEMO_MATCH)
    old_run_id = case.run.run_id

    # A reprocess moves the case to a new run.
    case.run = case.run.model_copy(update={"run_id": "run_brand_new"})
    crud.reprocess_case_atomic(db, crud.get_case(db, DEMO_MATCH), case)

    # The old worker now tries to commit its result.
    db_case = crud.get_case(db, DEMO_MATCH)
    stale = crud.map_db_to_schema(db_case)
    stale.workflow_status = schemas.WorkflowStatus.COMPLETED
    stale.updated_at = "2020-01-01T00:00:00Z"
    accepted = worker._commit_case(db, db_case, stale, old_run_id)

    assert accepted is False
    current = crud.map_db_to_schema(crud.get_case(db, DEMO_MATCH))
    assert current.workflow_status != schemas.WorkflowStatus.COMPLETED
    assert current.run.run_id == "run_brand_new"


def test_processing_twice_does_not_manufacture_a_second_assessment(db):
    """A rerun after a crash never re-finalizes an already frozen pass."""
    case = crud.create_case_with_job(db, DEMO_MATCH)
    run_id = case.run.run_id

    worker.process_case(DEMO_MATCH, job_id="job_1", job_run_id=run_id)
    first = crud.map_db_to_schema(crud.get_case(db, DEMO_MATCH))
    assert first.machine_assessment is not None
    history_length = len(first.history)

    worker.process_case(DEMO_MATCH, job_id="job_1", job_run_id=run_id)
    second = crud.map_db_to_schema(crud.get_case(db, DEMO_MATCH))
    assert second.machine_assessment.assessed_at == first.machine_assessment.assessed_at
    assert len(second.history) == history_length
    assert second.review == first.review


def test_a_superseded_job_is_a_no_op(db):
    case = crud.create_case_with_job(db, DEMO_MATCH)
    worker.process_case(DEMO_MATCH, job_id="job_old", job_run_id="run_that_is_gone")
    unchanged = crud.map_db_to_schema(crud.get_case(db, DEMO_MATCH))
    assert unchanged.machine_assessment is None
    assert unchanged.workflow_status == schemas.WorkflowStatus.PROCESSING
