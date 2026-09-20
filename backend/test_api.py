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

    print("Testing GET /reviews...")
    review_response = client.get("/reviews")
    if review_response.status_code == 200:
        reviews = review_response.json()
        print(f"Total open reviews: {len(reviews)}")
        if len(reviews) > 0:
            review_item = reviews[0]
            review_id = review_item["review"]["review_id"]
            run_id = review_item["review"]["run_id"]
            
            print(f"Testing POST /reviews/{review_id}/notified...")
            notify_resp = client.post(f"/reviews/{review_id}/notified", json={"run_id": run_id})
            print(f"Notified Status Code: {notify_resp.status_code}")
            
            print(f"Testing POST /reviews/{review_id}/decision...")
            decision_payload = {
                "review_id": review_id,
                "run_id": run_id,
                "channel": "DASHBOARD",
                "actor_id": "user_123",
                "action": "PROVIDE_VALUE",
                "field": "gross_weight_kg",
                "side": "BL",
                "value": "15000",
                "override_confirmation": {
                    "review_id": review_id,
                    "run_id": run_id,
                    "field": "gross_weight_kg",
                    "side": "BL",
                    "proposed_value": "15000",
                    "confirmed": True
                }
            }
            decision_resp = client.post(f"/reviews/{review_id}/decision", json=decision_payload)
            print(f"Decision Status Code: {decision_resp.status_code}")
            
            # Check if case went back to processing
            case_resp = client.get(f"/cases/{case_id}")
            print(f"Workflow status after decision: {case_resp.json()['workflow_status']}")
    else:
        print("Error in /reviews endpoint:", review_response.text)
    dup_response = client.post("/cases", json=demo_email_payload)
    print(f"Duplicate Status Code: {dup_response.status_code} (Expected 200)")
    
    print("Testing GET /cases list endpoint...")
    list_response = client.get("/cases")
    if list_response.status_code == 200:
        cases_list = list_response.json()
        print(f"Total cases returned: {len(cases_list)}")
    else:
        print("Error in list endpoint:", list_response.text)
