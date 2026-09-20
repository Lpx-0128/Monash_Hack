import time
import uuid
import pytest
from backend import schemas
from backend.export import export_eval_cases


def poll_case(client, case_id: str, expected_status: str, timeout: int = 15) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        resp = client.get(f"/api/v1/cases/{case_id}")
        if resp.status_code == 200:
            data = resp.json()
            if data["workflow_status"] == expected_status:
                return data
        time.sleep(0.3)
    resp = client.get(f"/api/v1/cases/{case_id}")
    raise AssertionError(
        f"Timed out waiting for {expected_status}. "
        f"Last status: {resp.json().get('workflow_status')} — {resp.text[:200]}"
    )


def test_health_and_ready(client):
    r_health = client.get("/health")
    assert r_health.status_code == 200
    assert r_health.json()["status"] == "OK"

    r_ready = client.get("/ready")
    assert r_ready.status_code == 200
    assert r_ready.json()["status"] == "READY"


def test_create_case_and_worker_pipeline(client):
    email_id = f"test_email_{uuid.uuid4().hex[:6]}"
    r = client.post("/api/v1/cases", json={"email_id": email_id})
    assert r.status_code == 202
    case_data = r.json()
    assert case_data["case_id"] == email_id
    assert case_data["workflow_status"] == "PROCESSING"

    # Poll until AWAITING_HUMAN
    awaiting = poll_case(client, email_id, "AWAITING_HUMAN", timeout=15)
    assert awaiting["machine_assessment"]["status"] == "NEEDS_REVIEW"
    assert awaiting["review"] is not None
    assert awaiting["review"]["status"] == "OPEN"

    # Verify Invariant 7: all 7 fields present
    assert len(awaiting["fields"]) == 7

    # Retrieve reviews
    rev_resp = client.get("/api/v1/reviews")
    assert rev_resp.status_code == 200
    reviews = rev_resp.json()
    matching_reviews = [rev for rev in reviews if rev["review"]["case_id"] == email_id]
    assert len(matching_reviews) == 1
    review = matching_reviews[0]["review"]
    review_id = review["review_id"]
    run_id = review["run_id"]

    # Mark notified
    notif_resp = client.post(f"/api/v1/reviews/{review_id}/notified", json={"run_id": run_id})
    assert notif_resp.status_code == 200
    assert notif_resp.json()["notified_at"] is not None

    # Submit decision PROVIDE_VALUE with 15000
    decision_payload = {
        "review_id": review_id,
        "run_id": run_id,
        "channel": "DASHBOARD",
        "actor_id": "user_123",
        "action": "PROVIDE_VALUE",
        "field": "gross_weight_kg",
        "side": "BL",
        "value": "15000",
    }
    dec_resp = client.post(f"/api/v1/reviews/{review_id}/decision", json=decision_payload)
    assert dec_resp.status_code == 202

    # Poll until COMPLETED
    completed = poll_case(client, email_id, "COMPLETED", timeout=15)
    assert completed["workflow_status"] == "COMPLETED"
    assert completed["follow_up"] == "NONE"
    assert completed["completed_at"] is not None
    assert completed["resolution"]["final_status"] == "OK"

    # Verify submitted value is saved in gross_weight_kg
    gw_field = next(f for f in completed["fields"] if f["field"] == "gross_weight_kg")
    assert gw_field["result"] == "MATCH"
    assert gw_field["bl"]["raw"] == "15000"
    assert gw_field["bl"]["normalized"] == 15000

    # Verify history events
    history_types = [h["type"] for h in completed["history"]]
    assert "CASE_CREATED" in history_types
    assert "EMAIL_CLASSIFIED" in history_types
    assert "REVIEW_CREATED" in history_types
    assert "REVIEW_NOTIFIED" in history_types
    assert "DECISION_RECEIVED" in history_types
    assert "DECISION_APPLIED" in history_types
    assert "CASE_COMPLETED" in history_types

    # Duplicate decision should 409
    dup_resp = client.post(f"/api/v1/reviews/{review_id}/decision", json=decision_payload)
    assert dup_resp.status_code == 409
    assert dup_resp.json()["error"]["code"] == "REVIEW_ALREADY_CLOSED"


def test_reprocess_safety(client):
    email_id = f"reprocess_email_{uuid.uuid4().hex[:6]}"
    r = client.post("/api/v1/cases", json={"email_id": email_id})
    assert r.status_code == 202

    poll_case(client, email_id, "AWAITING_HUMAN", timeout=15)

    # Reprocess
    reproc = client.post(f"/api/v1/cases/{email_id}/reprocess")
    assert reproc.status_code == 202
    new_run_id = reproc.json()["run"]["run_id"]

    # Poll until AWAITING_HUMAN on new run
    reprocessed = poll_case(client, email_id, "AWAITING_HUMAN", timeout=15)
    assert reprocessed["run"]["run_id"] == new_run_id
    assert reprocessed["review"]["run_id"] == new_run_id


def test_acknowledge_decision_blocks_external(client):
    email_id = f"ack_email_{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/cases", json={"email_id": email_id})
    case = poll_case(client, email_id, "AWAITING_HUMAN", timeout=15)

    review = case["review"]
    ack_payload = {
        "review_id": review["review_id"],
        "run_id": review["run_id"],
        "channel": "DASHBOARD",
        "actor_id": "operator_1",
        "action": "ACKNOWLEDGE",
        "user_message": "Document unavailable externally",
    }
    r = client.post(f"/api/v1/reviews/{review['review_id']}/decision", json=ack_payload)
    assert r.status_code == 202
    data = r.json()
    assert data["workflow_status"] == "BLOCKED_EXTERNAL"
    assert data["follow_up"] == "AWAIT_EXTERNAL"
    assert data["review"]["status"] == "CLOSED"


def test_decision_validation_errors(client):
    email_id = f"val_email_{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/cases", json={"email_id": email_id})
    case = poll_case(client, email_id, "AWAITING_HUMAN", timeout=15)
    review = case["review"]

    # Action not allowed
    bad_action = {
        "review_id": review["review_id"],
        "run_id": review["run_id"],
        "channel": "DASHBOARD",
        "actor_id": "user_1",
        "action": "SELECT_OPTION",
        "option_id": "opt_123",
    }
    r1 = client.post(f"/api/v1/reviews/{review['review_id']}/decision", json=bad_action)
    assert r1.status_code == 422
    assert r1.json()["error"]["code"] == "ACTION_NOT_ALLOWED"

    # Missing value for PROVIDE_VALUE
    bad_value = {
        "review_id": review["review_id"],
        "run_id": review["run_id"],
        "channel": "DASHBOARD",
        "actor_id": "user_1",
        "action": "PROVIDE_VALUE",
        "field": "gross_weight_kg",
        "side": "BL",
        "value": "",
    }
    r2 = client.post(f"/api/v1/reviews/{review['review_id']}/decision", json=bad_value)
    assert r2.status_code == 422
    assert r2.json()["error"]["code"] == "INVALID_VALUE"


def test_security_eval_isolation(client):
    eval_email_id = f"eval_secret_{uuid.uuid4().hex[:6]}"
    # Create with EVAL scope
    r = client.post("/api/v1/cases", json={"email_id": eval_email_id}, headers={"X-Run-Kind": "EVAL"})
    assert r.status_code == 202
    assert r.json()["run"]["kind"] == "EVAL"

    # Public user trying to query ?run_kind=EVAL without header gets DEMO list
    r_list = client.get("/api/v1/cases?run_kind=EVAL")
    assert r_list.status_code == 200
    for c in r_list.json():
        assert c["run_kind"] == "DEMO"

    # Public user requesting the specific EVAL case gets 404
    r_read = client.get(f"/api/v1/cases/{eval_email_id}")
    assert r_read.status_code == 404
    assert r_read.json()["error"]["code"] == "NOT_FOUND"

    # Public user trying to reprocess gets 404
    r_reproc = client.post(f"/api/v1/cases/{eval_email_id}/reprocess")
    assert r_reproc.status_code == 404


def test_stats_metrics(client):
    r = client.get("/api/v1/stats")
    assert r.status_code == 200
    stats = r.json()
    assert "total_cases" in stats
    assert "by_workflow" in stats
    assert "by_category" in stats
    assert "auto_completed" in stats
    assert "awaiting_human_now" in stats
