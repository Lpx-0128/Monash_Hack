import threading
import time
from . import crud, worker, schemas
from .database import SessionLocal

def _process_job(job):
    """Process a single job based on its action."""
    if job.action == "PROCESS_CASE":
        worker.process_case(job.case_id, job.job_id)
    elif job.action == "APPLY_DECISION":
        worker.apply_decision(job.case_id, job.job_id)
    else:
        # Unknown action – mark as FAILED
        crud.update_job_status(SessionLocal(), job.job_id, "FAILED", error=f"Unknown action {job.action}")

def worker_loop(stop_event: threading.Event = None, poll_interval: int = 5):
    """Continuously poll pending jobs and process them.

    This function is intended to be run in a background thread started on FastAPI startup.
    """
    if stop_event is None:
        stop_event = threading.Event()
    while not stop_event.is_set():
        db = SessionLocal()
        try:
            pending = crud.get_pending_jobs(db)
            for job in pending:
                # Mark job as RUNNING before processing to avoid duplicate workers
                crud.update_job_status(db, job.job_id, "RUNNING")
                try:
                    _process_job(job)
                except Exception as e:
                    # On error, mark FAILED with error message
                    crud.update_job_status(db, job.job_id, "FAILED", error=str(e))
        finally:
            db.close()
        time.sleep(poll_interval)

def start_worker_thread():
    """Start the worker loop in a daemon thread."""
    thread = threading.Thread(target=worker_loop, daemon=True)
    thread.start()
    return thread
