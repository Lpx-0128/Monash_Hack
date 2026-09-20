"""Durable polling worker loop.

Rules:
- Jobs are claimed atomically with a conditional UPDATE WHERE status='PENDING'.
- On startup, any job left RUNNING by a previous crash is reset to PENDING.
- Each job is retried exactly once before being permanently marked FAILED.
- The loop is never started as an import side effect; call start_worker_thread() explicitly.
"""

import threading
import time
import logging
from sqlalchemy import text
from . import crud, worker
from .database import SessionLocal

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # try once, retry once, then FAILED


def _recover_stale_running_jobs(db):
    """Reset any RUNNING jobs left over from a previous process crash."""
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    result = db.execute(
        text(
            "UPDATE jobs SET status='PENDING', updated_at=:now WHERE status='RUNNING'"
        ),
        {"now": now}
    )
    db.commit()
    if result.rowcount:
        logger.warning("Recovered %d stale RUNNING jobs on startup", result.rowcount)


def _claim_job(db):
    """Atomically claim one PENDING job by setting it to RUNNING.

    Uses a conditional UPDATE so two concurrent workers cannot both claim the
    same job.  Returns the claimed JobModel or None.
    """
    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Find the oldest PENDING job
    from . import models
    job = db.query(models.JobModel).filter(models.JobModel.status == "PENDING").order_by(models.JobModel.created_at).first()
    if job is None:
        return None
    # Atomic compare-and-set: only update if still PENDING
    updated = db.execute(
        text(
            "UPDATE jobs SET status='RUNNING', updated_at=:now WHERE job_id=:job_id AND status='PENDING'"
        ),
        {"now": now, "job_id": job.job_id}
    ).rowcount
    db.commit()
    if updated == 0:
        # Another worker beat us to it
        return None
    db.refresh(job)
    return job


def _process_job(job):
    """Dispatch a job to the appropriate worker function."""
    if job.action == "PROCESS_CASE":
        worker.process_case(job.case_id, job.job_id)
    elif job.action == "APPLY_DECISION":
        worker.apply_decision(job.case_id, job.job_id)
    else:
        raise ValueError(f"Unknown job action: {job.action}")


def _handle_job_failure(db, job, error_msg: str):
    """Record a failed attempt. Retry once; permanently FAIL after MAX_ATTEMPTS."""
    import json
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    attempts = list(job.attempts or [])
    attempts.append({"at": now, "error": error_msg})

    if len(attempts) < MAX_ATTEMPTS:
        # Still have a retry left — reset to PENDING
        logger.warning("Job %s failed (attempt %d/%d), will retry: %s", job.job_id, len(attempts), MAX_ATTEMPTS, error_msg)
        from . import models
        db.execute(
            text("UPDATE jobs SET status='PENDING', attempts=:attempts, updated_at=:now WHERE job_id=:job_id"),
            {"attempts": json.dumps(attempts), "now": now, "job_id": job.job_id}
        )
    else:
        # Exhausted retries — permanently FAILED
        logger.error("Job %s permanently FAILED after %d attempts: %s", job.job_id, len(attempts), error_msg)
        db.execute(
            text("UPDATE jobs SET status='FAILED', attempts=:attempts, updated_at=:now WHERE job_id=:job_id"),
            {"attempts": json.dumps(attempts), "now": now, "job_id": job.job_id}
        )
        # Mark the case itself as FAILED with a contract-shaped failure record
        _mark_case_failed(db, job.case_id, error_msg, now, attempts)
    db.commit()


def _mark_case_failed(db, case_id: str, error_msg: str, now: str, attempts: list):
    """Set the case workflow_status to FAILED and write a contract-shaped failure record."""
    db_case = crud.get_case(db, case_id)
    if db_case is None:
        return
    schema_case = crud.map_db_to_schema(db_case)
    from . import schemas
    import uuid
    schema_case.workflow_status = schemas.WorkflowStatus.FAILED
    # Contract §9 failure shape: {step, message, attempts}
    schema_case.failure = {
        "step": "WORKER",
        "message": error_msg,
        "attempts": attempts,
    }
    schema_case.updated_at = now
    schema_case.history.append(
        schemas.HistoryEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            run_id=schema_case.run.run_id,
            at=now,
            type="WORKER_FAILED",
            actor=schemas.Actor(kind="SYSTEM", id=None),
            summary=f"Worker permanently failed: {error_msg[:120]}"
        )
    )
    crud.update_case(db, db_case, schema_case)


def worker_loop(stop_event: threading.Event = None, poll_interval: int = 5):
    """Continuously poll and process pending jobs.

    On first iteration, recovers any stale RUNNING jobs from a previous crash.
    """
    if stop_event is None:
        stop_event = threading.Event()

    first_run = True
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            if first_run:
                _recover_stale_running_jobs(db)
                first_run = False

            job = _claim_job(db)
            if job is not None:
                try:
                    _process_job(job)
                    crud.update_job_status(db, job.job_id, "COMPLETED")
                except Exception as exc:
                    _handle_job_failure(db, job, str(exc))
                # Do NOT sleep — drain the queue before resting
                continue
        except Exception as outer_exc:
            logger.exception("Unexpected error in worker loop: %s", outer_exc)
        finally:
            db.close()

        # Only sleep when there was nothing to do
        time.sleep(poll_interval)


def start_worker_thread(poll_interval: int = 5) -> threading.Thread:
    """Start the worker loop in a daemon thread. Call this exactly once at app startup."""
    thread = threading.Thread(target=worker_loop, kwargs={"poll_interval": poll_interval}, daemon=True, name="worker-loop")
    thread.start()
    logger.info("Worker loop started (thread: %s)", thread.name)
    return thread
