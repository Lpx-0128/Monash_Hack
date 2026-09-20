from sqlalchemy import Column, String, JSON
from .database import Base

class CaseModel(Base):
    __tablename__ = "cases"

    case_id = Column(String, primary_key=True, index=True)
    schema_version = Column(String, default="2.1.1")
    workflow_status = Column(String, nullable=False)
    machine_assessment = Column(JSON, nullable=True)
    resolution = Column(JSON, nullable=True)
    follow_up = Column(String, nullable=False)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
    completed_at = Column(String, nullable=True)

    # Nested JSON objects
    run = Column(JSON, nullable=False)
    email = Column(JSON, nullable=False)
    documents = Column(JSON, default=list)
    fields_data = Column(JSON, default=list) # named fields_data to avoid 'fields' conflict if any
    review = Column(JSON, nullable=True)
    failure = Column(JSON, nullable=True)
    history = Column(JSON, default=list)
    metrics = Column(JSON, nullable=False)

class JobModel(Base):
    __tablename__ = "jobs"
    
    job_id = Column(String, primary_key=True)
    case_id = Column(String, index=True, nullable=False)
    run_id = Column(String, nullable=False)
    action = Column(String, nullable=False) # e.g. "PROCESS_CASE", "APPLY_DECISION"
    status = Column(String, nullable=False, default="PENDING") # PENDING, RUNNING, COMPLETED, FAILED
    attempts = Column(JSON, default=list) # List of failure records
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
