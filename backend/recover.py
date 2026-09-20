import time
from sqlalchemy.orm import Session
from .database import SessionLocal
from . import crud
from . import worker
from . import models

def recover_jobs():
    db: Session = SessionLocal()
    try:
        # Get all PENDING and RUNNING jobs
        jobs = db.query(models.JobModel).filter(
            models.JobModel.status.in_(["PENDING", "RUNNING"])
        ).all()
        
        if not jobs:
            print("No pending or stuck jobs found.")
            return
            
        print(f"Found {len(jobs)} pending/stuck jobs. Recovering...")
        
        for job in jobs:
            print(f"Recovering Job {job.job_id} for Case {job.case_id} (Action: {job.action})...")
            
            # Reset status to PENDING
            crud.update_job_status(db, job.job_id, "PENDING")
            
            # Run the job synchronously (or this could re-queue in a real distributed task system)
            if job.action == "PROCESS_CASE":
                worker.process_case(job.case_id, job.job_id)
            elif job.action == "APPLY_DECISION":
                worker.apply_decision(job.case_id, job.job_id)
            else:
                crud.update_job_status(db, job.job_id, "FAILED", error=f"Unknown action {job.action}")
                
            print(f"Job {job.job_id} recovered.")
            
    finally:
        db.close()

if __name__ == "__main__":
    recover_jobs()
