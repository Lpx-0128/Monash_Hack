from fastapi import FastAPI, Depends, HTTPException
from sqlalchemy.orm import Session
from . import schemas, models, crud
from .database import engine, get_db

# Create the database tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Shipping Document Verification API", version="2.1.1")

@app.get("/health")
def health_check():
    return {"status": "OK", "version": "2.1.1"}

@app.post("/cases", response_model=schemas.Case)
def create_case(case: schemas.Case, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=case.case_id)
    if db_case:
        # Contract §8: duplicate POST /cases for existing DEMO case should return 200 with current case
        return crud.map_db_to_schema(db_case)
    return crud.create_case(db=db, case=case)

@app.get("/cases/{case_id}", response_model=schemas.Case)
def read_case(case_id: str, db: Session = Depends(get_db)):
    db_case = crud.get_case(db, case_id=case_id)
    if db_case is None:
        raise HTTPException(status_code=404, detail="Case not found")
    return crud.map_db_to_schema(db_case)
