import pytest
import uuid
from backend import schemas
from tests.test_api import poll_case


def test_escape_route_none_of_these(client):
    email_id = f"escape_email_{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/cases", json={"email_id": email_id})

    # Poll until AWAITING_HUMAN to ensure review is ready
    case = poll_case(client, email_id, "AWAITING_HUMAN", timeout=15)
    review = case["review"]
    assert review is not None

    escape_payload = {
        "review_id": review["review_id"],
        "run_id": review["run_id"],
        "channel": "DASHBOARD",
        "actor_id": "operator_escape",
        "action": "SELECT_OPTION",
        "option_id": "NONE_OF_THESE"
    }
    r = client.post(f"/api/v1/reviews/{review['review_id']}/decision", json=escape_payload)
    assert r.status_code == 202
    data = r.json()
    assert data["workflow_status"] == "BLOCKED_EXTERNAL"
    assert data["follow_up"] == "AWAIT_EXTERNAL"
    assert data["review"]["status"] == "CLOSED"


def test_escape_route_user_cant_tell(client):
    email_id = f"cant_tell_email_{uuid.uuid4().hex[:6]}"
    client.post("/api/v1/cases", json={"email_id": email_id})

    case = poll_case(client, email_id, "AWAITING_HUMAN", timeout=15)
    review = case["review"]
    assert review is not None

    cant_tell_payload = {
        "review_id": review["review_id"],
        "run_id": review["run_id"],
        "channel": "TELEGRAM",
        "actor_id": "telegram_user",
        "action": "PROVIDE_VALUE",
        "field": "gross_weight_kg",
        "side": "BL",
        "value": "123",
        "user_message": "I can't tell"
    }
    r = client.post(f"/api/v1/reviews/{review['review_id']}/decision", json=cant_tell_payload)
    assert r.status_code == 202
    data = r.json()
    assert data["workflow_status"] == "BLOCKED_EXTERNAL"
    assert data["follow_up"] == "AWAIT_EXTERNAL"


def test_batch_ingestion_endpoint(client):
    batch_payload = {
        "email_ids": [
            f"batch_1_{uuid.uuid4().hex[:4]}",
            f"batch_2_{uuid.uuid4().hex[:4]}",
            f"batch_3_{uuid.uuid4().hex[:4]}",
        ]
    }
    r = client.post("/api/v1/cases/batch", json=batch_payload)
    assert r.status_code == 202
    data = r.json()
    assert data["total_requested"] == 3
    assert data["created"] == 3
    assert len(data["case_ids"]) == 3

    # Sending again: existing count increases
    r2 = client.post("/api/v1/cases/batch", json=batch_payload)
    assert r2.status_code == 202
    data2 = r2.json()
    assert data2["existing"] == 3
    assert data2["created"] == 0
