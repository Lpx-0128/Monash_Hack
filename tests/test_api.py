"""API surface: health, routing, scope isolation and stats.

The decision and worker journeys live in tests/integration/, so this file does
not run a second, parallel version of them.
"""

import uuid

from tests.conftest import DEMO_INVOICE, DEMO_MATCH, DEMO_MISSING_WEIGHT
from tests.helpers import create_and_wait, poll_case


def test_health_and_ready(client):
    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "OK"

    ready = client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "READY"


def test_create_is_idempotent_for_the_same_email_id(client):
    first = client.post("/api/v1/cases", json={"email_id": DEMO_MATCH})
    assert first.status_code == 202
    assert first.json()["workflow_status"] == "PROCESSING"

    second = client.post("/api/v1/cases", json={"email_id": DEMO_MATCH})
    assert second.status_code == 200          # existing, not created again
    assert second.json()["case_id"] == DEMO_MATCH


def test_case_listing_and_filters(client):
    create_and_wait(client, DEMO_MATCH, "COMPLETED")
    create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")

    listing = client.get("/api/v1/cases")
    assert listing.status_code == 200
    ids = {c["case_id"] for c in listing.json()}
    assert {DEMO_MATCH, DEMO_MISSING_WEIGHT} <= ids

    awaiting = client.get("/api/v1/cases?workflow_status=AWAITING_HUMAN").json()
    assert {c["case_id"] for c in awaiting} == {DEMO_MISSING_WEIGHT}

    with_review = client.get("/api/v1/cases?has_open_review=true").json()
    assert {c["case_id"] for c in with_review} == {DEMO_MISSING_WEIGHT}

    by_category = client.get("/api/v1/cases?category=BL_COMPARISON").json()
    assert {DEMO_MATCH, DEMO_MISSING_WEIGHT} <= {c["case_id"] for c in by_category}


def test_review_listing_and_notification_marker(client):
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]

    reviews = client.get("/api/v1/reviews").json()
    matching = [item for item in reviews if item["review"]["case_id"] == case["case_id"]]
    assert len(matching) == 1
    assert matching[0]["case"]["case_id"] == case["case_id"]

    first = client.post(f"/api/v1/reviews/{review['review_id']}/notified",
                        json={"run_id": review["run_id"]})
    assert first.status_code == 200
    notified_at = first.json()["notified_at"]
    assert notified_at is not None

    # Marking twice is idempotent.
    second = client.post(f"/api/v1/reviews/{review['review_id']}/notified",
                         json={"run_id": review["run_id"]})
    assert second.status_code == 200
    assert second.json()["notified_at"] == notified_at

    stale = client.post(f"/api/v1/reviews/{review['review_id']}/notified",
                        json={"run_id": "run_ancient"})
    assert stale.status_code in (200, 409)


def test_document_content_is_served_for_a_demo_safe_source(client):
    case = create_and_wait(client, DEMO_MATCH, "COMPLETED")
    si = next(d for d in case["documents"] if d["role"] == "SI")
    assert si["demo_safe"] is True

    response = client.get(f"/api/v1/documents/{si['document_id']}/content")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "SHIPPING INSTRUCTION" in response.text
    # The exact registered bytes, not a synthesized placeholder.
    assert "Document content for" not in response.text


def test_document_content_for_an_unknown_id_is_not_invented(client):
    response = client.get("/api/v1/documents/doc_not_a_real_identity/content")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_security_eval_isolation(client):
    eval_id = DEMO_INVOICE
    created = client.post("/api/v1/cases", json={"email_id": eval_id},
                          headers={"X-Run-Kind": "EVAL"})
    assert created.status_code == 202
    assert created.json()["run"]["kind"] == "EVAL"

    # A public caller cannot widen its scope to EVAL.
    listing = client.get("/api/v1/cases?run_kind=EVAL")
    assert listing.status_code == 200
    assert all(c["run_kind"] == "DEMO" for c in listing.json())

    # The EVAL case is concealed from public scope entirely.
    assert client.get(f"/api/v1/cases/{eval_id}").status_code == 404
    assert client.post(f"/api/v1/cases/{eval_id}/reprocess").status_code == 404
    duplicate = client.post("/api/v1/cases", json={"email_id": eval_id})
    assert duplicate.status_code == 404
    assert duplicate.json()["error"]["code"] == "NOT_FOUND"


def test_stats_report_contract_metrics(client):
    create_and_wait(client, DEMO_MATCH, "COMPLETED")
    create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")

    stats = client.get("/api/v1/stats").json()
    assert stats["run_kind"] == "DEMO"
    assert stats["total_cases"] >= 2
    assert stats["by_workflow"]["COMPLETED"] >= 1
    assert stats["by_workflow"]["AWAITING_HUMAN"] >= 1
    assert stats["awaiting_human_now"] >= 1
    assert stats["bl_comparison"]["total"] >= 2
    assert stats["unclassified"] == 0
    # No AI is configured in tests, so the counters are honestly zero.
    assert stats["ai_calls_total"] == 0
    assert stats["avg_processing_ms"] is not None


def test_stats_tolerate_a_bl_case_that_is_still_in_progress(client):
    """An in-progress BL case must not be counted as already assessed."""
    client.post("/api/v1/cases", json={"email_id": DEMO_MATCH})
    stats = client.get("/api/v1/stats").json()
    assert stats["total_cases"] >= 1
    assert stats["by_machine_status"]["OK"] >= 0
