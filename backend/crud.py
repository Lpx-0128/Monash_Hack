from sqlalchemy.orm import Session
from . import models, schemas
import json

def get_case(db: Session, case_id: str):
    return db.query(models.CaseModel).filter(models.CaseModel.case_id == case_id).first()

def create_case(db: Session, case: schemas.Case):
    # Convert Pydantic model to dict, then to JSON-serializable dict
    # by using model_dump(mode='json') in pydantic v2
    case_data = case.model_dump(mode='json', by_alias=True)
    
    # Extract fields for direct columns
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
        
        # JSON columns
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
    
    # Rename fields_data back to fields to match Pydantic model
    return map_db_to_schema(db_case)

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
        "review": db_case.review,
        "failure": db_case.failure,
        "history": db_case.history,
        "metrics": db_case.metrics,
    }
    return schemas.Case(**data)
