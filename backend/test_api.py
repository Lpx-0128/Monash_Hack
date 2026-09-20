import json
from fastapi.testclient import TestClient
from backend.main import app
from backend.schemas import Case
import os
import time

# Remove test database if it exists to start fresh
if os.path.exists("shipping.db"):
    try:
        os.remove("shipping.db")
    except Exception as e:
        print(f"Could not remove db: {e}")

client = TestClient(app)

import uuid

demo_email_payload = {
    "email_id": f"test_email_{uuid.uuid4().hex[:6]}"
}

if __name__ == "__main__":
    print("Testing POST /cases...")
    response = client.post("/cases", json=demo_email_payload)
    print(f"Status Code: {response.status_code}")
    if response.status_code != 202:
        print("Error details:", response.text)
        exit(1)
    
    case_data = response.json()
    case_id = case_data["case_id"]
    print(f"Created Case ID: {case_id} with status {case_data['workflow_status']}")
    
    print("Waiting 3 seconds for background worker to process...")
    time.sleep(3)
    
    print(f"Testing GET /cases/{case_id}...")
    response = client.get(f"/cases/{case_id}")
    if response.status_code == 200:
        data = response.json()
        print(f"Workflow status is now: {data['workflow_status']}")
        print(f"Machine status is: {data['machine_assessment']['status']}")
    else:
        print("Error details:", response.text)

    print("Testing duplicate POST /cases...")
    dup_response = client.post("/cases", json=demo_email_payload)
    print(f"Duplicate Status Code: {dup_response.status_code} (Expected 200)")
    
    print("Testing GET /cases list endpoint...")
    list_response = client.get("/cases")
    if list_response.status_code == 200:
        cases_list = list_response.json()
        print(f"Total cases returned: {len(cases_list)}")
    else:
        print("Error in list endpoint:", list_response.text)
