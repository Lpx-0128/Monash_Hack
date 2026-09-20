"""Durable polling worker loop.

Rules:
- Jobs are claimed atomically: UPDATE jobs SET status='RUNNING' WHERE status='PENDING'.
- On startup, RUNNING jobs left by a crashed process are reset to PENDING.
- Each job is retried exactly once (MAX_ATTEMPTS=2) before being permanently FAILED.
- COMPLETED is written with WHERE status='RUNNING' so a SUPERSEDED job is never
  marked COMPLETED after a reprocess.
- The loop is never started as an import side effect; call start_worker_thread().
"""

import threading
import time
import logging
import json
from datetime import datetime, timezone
from sqlalchemy import text
from . import crud, worker, schemas
from .database import SessionLocal

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 2  # try once, retry once, then permanently FAILED


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _recover_stale_running_jobs(db):
    """Reset RUNNING jobs left over from a previous process crash."""
    now = _now()
    result = db.execute(
        text("UPDATE jobs SET status='PENDING', updated_at=:now WHERE status='RUNNING'"),
        {"now": now}
    )
    db.commit()
    if result.rowcount:
        logger.warning("Recovered %d stale RUNNING jobs on startup", result.rowcount)


def _claim_job(db):
    """Atomically claim one PENDING job by setting it to RUNNING."""
    from . import models
    job = (
        db.query(models.JobModel)
        .filter(models.JobModel.status == "PENDING")
        .order_by(models.JobModel.created_at)
        .first()
    )
    if job is None:
        return None
    # Atomic compare-and-set: only update if still PENDING
    updated = db.execute(
        text(
            "UPDATE jobs SET status='RUNNING', updated_at=:now "
            "WHERE job_id=:job_id AND status='PENDING'"
        ),
        {"now": _now(), "job_id": job.job_id}
    ).rowcount
    db.commit()
    if updated == 0:
        return None  # Another worker beat us to it
    db.refresh(job)
    return job


def _complete_job(db, job_id: str):
    """Mark a job COMPLETED only if it is still RUNNING."""
    updated = db.execute(
        text(
            "UPDATE jobs SET status='COMPLETED', updated_at=:now "
            "WHERE job_id=:job_id AND status='RUNNING'"
        ),
        {"now": _now(), "job_id": job_id}
    ).rowcount
    db.commit()
    if updated == 0:
        logger.info("Job %s was SUPERSEDED; COMPLETED not written (expected)", job_id)


def _process_job(job):
    """Dispatch a job to the appropriate worker function, passing job.run_id."""
    if job.action == "PROCESS_CASE":
        worker.process_case(job.case_id, job.job_id, job.run_id)
    elif job.action == "APPLY_DECISION":
        worker.apply_decision(job.case_id, job.job_id, job.run_id)
    else:
        raise ValueError(f"Unknown job action: {job.action}")


def _emit_retry_triggered(db, case_id: str, job_id: str, attempt_no: int, error_msg: str):
    """Append a RETRY_TRIGGERED history event to the case."""
    db_case = crud.get_case(db, case_id)
    if db_case is None:
        return
    import uuid
    schema_case = crud.map_db_to_schema(db_case)
    now = _now()
    schema_case.history.append(
        schemas.HistoryEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            run_id=schema_case.run.run_id,
            at=now,
            type=schemas.HistoryEventType.RETRY_TRIGGERED.value,
            actor=schemas.Actor(kind="SYSTEM", id=None),
            summary=f"Job {job_id} attempt {attempt_no} failed, retrying: {error_msg[:120]}"
        )
    )
    crud.update_case(db, db_case, schema_case)


def _handle_job_failure(db, job, error_msg: str):
    """Record a failed attempt. Retry once; permanently FAIL after MAX_ATTEMPTS."""
    now = _now()
    attempts = list(job.attempts or [])
    attempts.append({"at": now, "error": error_msg})

    if len(attempts) < MAX_ATTEMPTS:
        # Retry path
        logger.warning("Job %s failed (attempt %d/%d), retrying: %s",
                       job.job_id, len(attempts), MAX_ATTEMPTS, error_msg)
        db.execute(
            text(
                "UPDATE jobs SET status='PENDING', attempts=:attempts, updated_at=:now "
                "WHERE job_id=:job_id"
            ),
            {"attempts": json.dumps(attempts), "now": now, "job_id": job.job_id}
        )
        db.commit()
        _emit_retry_triggered(db, job.case_id, job.job_id, len(attempts), error_msg)
    else:
        # Permanently FAILED
        logger.error("Job %s permanently FAILED after %d attempts: %s",
                     job.job_id, len(attempts), error_msg)
        db.execute(
            text(
                "UPDATE jobs SET status='FAILED', attempts=:attempts, updated_at=:now "
                "WHERE job_id=:job_id"
            ),
            {"attempts": json.dumps(attempts), "now": now, "job_id": job.job_id}
        )
        db.commit()
        _mark_case_failed(db, job.case_id, error_msg, now, len(attempts))


def _mark_case_failed(db, case_id: str, error_msg: str, now: str, attempt_count: int):
    """Set workflow_status=FAILED and write a contract-shaped failure record."""
    db_case = crud.get_case(db, case_id)
    if db_case is None:
        return
    import uuid
    schema_case = crud.map_db_to_schema(db_case)
    schema_case.workflow_status = schemas.WorkflowStatus.FAILED
    schema_case.failure = schemas.FailureDetail(
        step="WORKER",
        message=error_msg,
        attempts=attempt_count,
    )
    schema_case.updated_at = now
    schema_case.history.append(
        schemas.HistoryEvent(
            event_id=f"evt_{uuid.uuid4().hex[:8]}",
            run_id=schema_case.run.run_id,
            at=now,
            type=schemas.HistoryEventType.PROCESSING_FAILED.value,
            actor=schemas.Actor(kind="SYSTEM", id=None),
            summary=f"Worker permanently failed after {attempt_count} attempts: {error_msg[:120]}"
        )
    )
    crud.update_case(db, db_case, schema_case)


def worker_loop(stop_event: threading.Event = None, poll_interval: int = 1):
    """Continuously poll and process pending jobs."""
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
                    _complete_job(db, job.job_id)
                except Exception as exc:
                    _handle_job_failure(db, job, str(exc))
                continue
        except Exception as outer_exc:
            logger.exception("Unexpected error in worker loop: %s", outer_exc)
        finally:
            db.close()

        # Check stop_event during wait
        stop_event.wait(timeout=poll_interval)


_worker_thread = None
_stop_event = None


def start_worker_thread(poll_interval: int = 1) -> threading.Thread:
    """Start the worker loop in a daemon thread. Call exactly once at app startup."""
    global _worker_thread, _stop_event
    _stop_event = threading.Event()
    _worker_thread = threading.Thread(
        target=worker_loop,
        kwargs={"stop_event": _stop_event, "poll_interval": poll_interval},
        daemon=True,
        name="worker-loop"
    )
    _worker_thread.start()
    logger.info("Worker loop started (poll_interval=%ds, thread=%s)", poll_interval, _worker_thread.name)
    return _worker_thread


def stop_worker_thread():
    """Stop the worker loop gracefully."""
    global _worker_thread, _stop_event
    if _stop_event:
        _stop_event.set()
    if _worker_thread and _worker_thread.is_alive():
        _worker_thread.join(timeout=3)
