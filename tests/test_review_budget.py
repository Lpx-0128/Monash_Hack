"""Escape routes and batch ingestion, corrected against the contract.

The previous version sent NONE_OF_THESE to a VALUE_INPUT review and escaped a
PROVIDE_VALUE with free text. Both bypassed action validation, so they are
replaced here by a real CHOICE fixture, the allowed ACKNOWLEDGE action, and
explicit tests that the bypasses are refused.
"""

from tests.conftest import DEMO_DOCUMENT_CHOICE, DEMO_MATCH, DEMO_MISMATCH, DEMO_MISSING_WEIGHT
from tests.helpers import create_and_wait, poll_case


def test_none_of_these_on_a_real_choice_review(client):
    case = create_and_wait(client, DEMO_DOCUMENT_CHOICE, "AWAITING_HUMAN")
    review = case["review"]
    assert review["ui_mode"] == "CHOICE"

    response = client.post(
        f"/api/v1/reviews/{review['review_id']}/decision",
        json={"review_id": review["review_id"], "run_id": review["run_id"],
              "channel": "DASHBOARD", "actor_id": "operator_escape",
              "action": "SELECT_OPTION", "option_id": "NONE_OF_THESE"},
    )
    assert response.status_code == 202
    # Acceptance is durable; the block is recorded by the worker.
    assert response.json()["workflow_status"] == "PROCESSING"

    blocked = poll_case(client, case["case_id"], "BLOCKED_EXTERNAL")
    assert blocked["follow_up"] == "AWAIT_EXTERNAL"
    assert blocked["review"]["status"] == "CLOSED"
    assert blocked["resolution"]["final_status"] == "NEEDS_REVIEW"


def test_none_of_these_is_refused_on_a_value_input_review(client):
    """A VALUE_INPUT review has no options, so the escape option does not exist."""
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]
    assert review["ui_mode"] == "VALUE_INPUT"

    response = client.post(
        f"/api/v1/reviews/{review['review_id']}/decision",
        json={"review_id": review["review_id"], "run_id": review["run_id"],
              "channel": "DASHBOARD", "actor_id": "operator_escape",
              "action": "SELECT_OPTION", "option_id": "NONE_OF_THESE"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ACTION_NOT_ALLOWED"
    assert client.get(f"/api/v1/cases/{case['case_id']}").json()["review"]["status"] == "OPEN"


def test_i_cant_tell_uses_the_allowed_acknowledge_action(client):
    """"I can't tell" is the ACKNOWLEDGE action, not magic text in a message field."""
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]
    assert "ACKNOWLEDGE" in review["allowed_actions"]

    response = client.post(
        f"/api/v1/reviews/{review['review_id']}/decision",
        json={"review_id": review["review_id"], "run_id": review["run_id"],
              "channel": "TELEGRAM", "actor_id": "telegram_user",
              "action": "ACKNOWLEDGE", "user_message": "I can't tell"},
    )
    assert response.status_code == 202
    assert response.json()["workflow_status"] == "PROCESSING"

    blocked = poll_case(client, case["case_id"], "BLOCKED_EXTERNAL")
    assert blocked["follow_up"] == "AWAIT_EXTERNAL"
    assert blocked["resolution"]["user_message"] == "I can't tell"


def test_an_invalid_option_id_is_refused(client):
    case = create_and_wait(client, DEMO_DOCUMENT_CHOICE, "AWAITING_HUMAN")
    review = case["review"]
    response = client.post(
        f"/api/v1/reviews/{review['review_id']}/decision",
        json={"review_id": review["review_id"], "run_id": review["run_id"],
              "channel": "DASHBOARD", "actor_id": "op",
              "action": "SELECT_OPTION", "option_id": "opt_not_in_this_review"},
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "OPTION_NOT_FOUND"


def test_batch_ingestion_accepts_registered_ids(client):
    payload = {"email_ids": [DEMO_MATCH, DEMO_MISMATCH, DEMO_MISSING_WEIGHT]}
    first = client.post("/api/v1/cases/batch", json=payload)
    assert first.status_code == 202
    data = first.json()
    assert data["total_requested"] == 3
    assert data["created"] == 3
    assert len(data["case_ids"]) == 3

    second = client.post("/api/v1/cases/batch", json=payload)
    assert second.json()["existing"] == 3
    assert second.json()["created"] == 0


def test_batch_ingestion_skips_unregistered_ids(client):
    response = client.post("/api/v1/cases/batch",
                           json={"email_ids": [DEMO_MATCH, "email_not_registered"]})
    assert response.status_code == 202
    data = response.json()
    assert data["created"] == 1
    assert "email_not_registered" not in data["case_ids"]
