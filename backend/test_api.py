import json
from fastapi.testclient import TestClient
from backend.main import app
from backend.schemas import Case
import os
import time
import uuid

# Remove test database if it exists to start fresh
if os.path.exists("shipping.db"):
    try:
        os.remove("shipping.db")
    except Exception as e:
        print(f"Could not remove db: {e}")

client = TestClient(app)

demo_email_payload = {
    "email_id": f"test_email_{uuid.uuid4().hex[:6]}"
}

if __name__ == "__main__":
    print("=== Testing POST /cases ===")
    response = client.post("/cases", json=demo_email_payload)
    print(f"Status Code: {response.status_code}")
    assert response.status_code == 202, f"Expected 202, got {response.status_code}: {response.text}"
    
    case_data = response.json()
    case_id = case_data["case_id"]
    print(f"Created Case ID: {case_id} with status {case_data['workflow_status']}")
    
    print("\nWaiting 3 seconds for background worker to process...")
    time.sleep(3)
    
    print("=== Testing GET /cases/{case_id} ===")
    response = client.get(f"/cases/{case_id}")
    assert response.status_code == 200
    data = response.json()
    print(f"Workflow status: {data['workflow_status']}")
    print(f"Machine status: {data['machine_assessment']['status']}")
    
    print("\n=== Testing GET /reviews ===")
    review_response = client.get("/reviews")
    assert review_response.status_code == 200
    reviews = review_response.json()
    print(f"Total open reviews: {len(reviews)}")
    assert len(reviews) == 1, f"Expected 1 open review, got {len(reviews)}"
    
    review_item = reviews[0]
    review_id = review_item["review"]["review_id"]
    run_id = review_item["review"]["run_id"]
    
    print(f"\n=== Testing POST /reviews/{review_id}/decision ===")
    decision_payload = {
        "review_id": review_id,
        "run_id": run_id,
        "channel": "DASHBOARD",
        "actor_id": "user_123",
        "action": "PROVIDE_VALUE",
        "field": "gross_weight_kg",
        "side": "BL",
        "value": "15000"
    }
    decision_resp = client.post(f"/reviews/{review_id}/decision", json=decision_payload)
    print(f"Decision Status Code: {decision_resp.status_code}")
    assert decision_resp.status_code == 202
    
    print("\nWaiting 3 seconds for apply_decision to complete...")
    time.sleep(3)
    
    final_case_resp = client.get(f"/cases/{case_id}")
    final_case = final_case_resp.json()
    print(f"Final workflow status: {final_case['workflow_status']}")
    print(f"Final review status: {final_case['review']['status']}")
    assert final_case['workflow_status'] == 'COMPLETED', f"Expected COMPLETED, got {final_case['workflow_status']}"
    assert final_case['review']['status'] == 'CLOSED', f"Expected CLOSED, got {final_case['review']['status']}"
    
    print("\n=== Testing duplicate decision (should 409) ===")
    dup_decision = client.post(f"/reviews/{review_id}/decision", json=decision_payload)
    print(f"Duplicate decision Status Code: {dup_decision.status_code} (Expected 409)")
    assert dup_decision.status_code == 409
    
    print(f"\n=== Testing POST /cases/{case_id}/reprocess ===")
    reprocess_resp = client.post(f"/cases/{case_id}/reprocess")
    print(f"Reprocess Status Code: {reprocess_resp.status_code}")
    assert reprocess_resp.status_code == 202
    reprocess_data = reprocess_resp.json()
    print(f"New run_id: {reprocess_data['run']['run_id']}")
    print(f"Workflow status: {reprocess_data['workflow_status']}")
    assert reprocess_data['workflow_status'] == 'PROCESSING'
    
    print("\nWaiting 3 seconds for reprocessed worker...")
    time.sleep(3)
    
    reprocessed_case = client.get(f"/cases/{case_id}").json()
    print(f"Reprocessed workflow status: {reprocessed_case['workflow_status']}")
    
    print("\n=== Testing GET /cases with filters ===")
    filtered = client.get("/cases?workflow_status=AWAITING_HUMAN")
    print(f"Cases AWAITING_HUMAN: {len(filtered.json())}")
    
    print("\n=== Testing GET /stats ===")
    stats_resp = client.get("/stats")
    assert stats_resp.status_code == 200
    stats = stats_resp.json()
    print(f"Total cases: {stats['total_cases']}")
    print(f"By workflow: {stats['by_workflow']}")
    print(f"By category: {stats['by_category']}")
    
    print("\n=== Testing GET /ready ===")
    ready_resp = client.get("/ready")
    assert ready_resp.status_code == 200
    print(f"Ready: {ready_resp.json()}")
    
    print("\n=== Testing GET /documents/fake_id/content (placeholder) ===")
    doc_resp = client.get("/documents/fake_id/content")
    print(f"Document Status Code: {doc_resp.status_code} (Expected 404)")
    assert doc_resp.status_code == 404
    
    print("\n=== Testing duplicate POST /cases ===")
    dup_response = client.post("/cases", json=demo_email_payload)
    print(f"Duplicate Status Code: {dup_response.status_code} (Expected 200)")
    assert dup_response.status_code == 200
    
    print("\n[SUCCESS] All tests passed!")
