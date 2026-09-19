import json
from fastapi.testclient import TestClient
from backend.main import app
from backend.schemas import Case
import os
import time

# Remove test database if it exists to start fresh
if os.path.exists("shipping.db"):
    # Windows might keep a lock, just a precaution
    try:
        os.remove("shipping.db")
    except Exception as e:
        print(f"Could not remove db: {e}")

client = TestClient(app)

demo_payload = {
  "schema_version": "2.1.1",
  "case_id": "demo_email_001",
  "run": {
    "run_id": "demo_run_001",
    "kind": "DEMO",
    "started_at": "2026-09-19T09:00:00Z",
    "input_version": "synthetic-input-v1",
    "config_version": "pipeline-v1",
    "demo_safe": True
  },
  "email": {
    "email_id": "demo_email_001",
    "from": "demo@example.com",
    "subject": "Verify draft BL - synthetic fixture",
    "received_at": None,
    "category": None,
    "classified_by": None,
    "classification_reason": None
  },
  "documents": [],
  "workflow_status": "PROCESSING",
  "machine_assessment": None,
  "fields": [],
  "review": None,
  "resolution": None,
  "follow_up": "NONE",
  "failure": None,
  "history": [
    {
      "event_id": "event_001",
      "run_id": "demo_run_001",
      "at": "2026-09-19T09:00:00Z",
      "type": "CASE_CREATED",
      "actor": {
        "kind": "SYSTEM",
        "id": None
      },
      "summary": "Synthetic demo run queued.",
      "details": None
    }
  ],
  "metrics": {
    "ai_calls": 0,
    "ai_assisted_fields": 0,
    "processing_ms": None,
    "est_ai_cost_usd": None
  },
  "created_at": "2026-09-19T09:00:00Z",
  "updated_at": "2026-09-19T09:00:00Z",
  "completed_at": None
}

if __name__ == "__main__":
    print("Testing Pydantic schema...")
    case = Case.model_validate(demo_payload)
    print("Successfully validated Case schema!")
    
    print("Testing POST /cases...")
    response = client.post("/cases", json=demo_payload)
    print(f"Status Code: {response.status_code}")
    if response.status_code != 200:
        print("Error details:", response.text)
    
    print("Testing GET /cases/demo_email_001...")
    response = client.get("/cases/demo_email_001")
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        data = response.json()
        print("Successfully retrieved case from database!")
        print(f"Email ID matched: {data['email']['email_id'] == 'demo_email_001'}")
        print(f"Received At matched: {data['email']['received_at'] == None}")
    else:
        print("Error details:", response.text)
