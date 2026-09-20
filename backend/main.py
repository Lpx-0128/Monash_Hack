from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from typing import List
from . import schemas, models, crud, worker
from .database import engine, get_db

# Create the database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Shipping Document Verification API", version="2.1.1")

@app.get("/health")
def health_check():
    return {"status": "OK", "version": "2.1.1"}

@app.get("/cases", response_model=List[schemas.CaseSummary])
def list_cases(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    cases = crud.get_cases(db, skip=skip, limit=limit)
    return [crud.map_case_to_summary(crud.map_db_to_schema(c)) for c in cases]

from fastapi import Response

@app.post("/cases", response_model=schemas.Case, status_code=status.HTTP_202_ACCEPTED)
def create_case(req: schemas.CreateCaseRequest, background_tasks: BackgroundTasks, response: Response, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=req.email_id)
    if db_case:
        # Contract §8: duplicate POST /cases for existing DEMO case should return 200 with current case
        response.status_code = status.HTTP_200_OK
        return crud.map_db_to_schema(db_case)
    
    # Create the case in PROCESSING state
    case = crud.create_initial_case(db, req.email_id)
    
    # Trigger the background worker
    background_tasks.add_task(worker.process_case, case.case_id)
    
    return case

@app.get("/cases/{case_id}", response_model=schemas.Case)
def read_case(case_id: str, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=case_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return crud.map_db_to_schema(db_case)
