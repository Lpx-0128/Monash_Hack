from fastapi import FastAPI
from .schemas import Case

app = FastAPI(title="Shipping Document Verification API", version="2.1.1")

@app.get("/health")
def health_check():
    return {"status": "OK", "version": "2.1.1"}

@app.post("/cases", response_model=Case)
def create_case(case: Case):
    # For now, just return the exact payload sent (echo) for testing validation
    return case
