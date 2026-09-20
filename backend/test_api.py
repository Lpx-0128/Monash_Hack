import json
import os
import time
import uuid

from fastapi.testclient import TestClient
from backend.main import app
from backend.schemas import Case

# TestClient with use_lifespan=True starts the worker loop exactly as production does
client = TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def poll_case(case_id: str, expected_status: str, timeout: int = 15) -> dict:
    """Poll GET /api/v1/cases/{case_id} until workflow_status matches or timeout."""
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


# ---------------------------------------------------------------------------
# Test runner
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Clean slate — must be inside __main__ so the import doesn't race the DB
    if os.path.exists("shipping.db"):
        try:
            os.remove("shipping.db")
        except Exception as e:
            print(f"Could not remove db: {e}")

    demo_email_payload = {"email_id": f"test_email_{uuid.uuid4().hex[:6]}"}

    # ── Health / ready (root paths, no /api/v1 prefix) ────────────────────
    print("=== GET /health ===")
    r = client.get("/health")
    assert r.status_code == 200, r.text
    print(f"  {r.json()}")

    print("=== GET /ready ===")
    r = client.get("/ready")
    assert r.status_code == 200, r.text
    print(f"  {r.json()}")

    # ── Create case ───────────────────────────────────────────────────────
    print("\n=== POST /api/v1/cases ===")
    r = client.post("/api/v1/cases", json=demo_email_payload)
    assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
    case_id = r.json()["case_id"]
    print(f"  Created {case_id}")

    # ── Wait for worker to produce a review ───────────────────────────────
    print("  Polling for AWAITING_HUMAN...")
    data = poll_case(case_id, "AWAITING_HUMAN", timeout=15)
    print(f"  Machine status: {data['machine_assessment']['status']}")

    # ── List reviews ──────────────────────────────────────────────────────
    print("\n=== GET /api/v1/reviews ===")
    r = client.get("/api/v1/reviews")
    assert r.status_code == 200
    reviews = r.json()
    assert len(reviews) == 1, f"Expected 1 open review, got {len(reviews)}"
    review_id = reviews[0]["review"]["review_id"]
    run_id = reviews[0]["review"]["run_id"]
    print(f"  review_id={review_id}, run_id={run_id}")

    # ── Submit decision ───────────────────────────────────────────────────
    print(f"\n=== POST /api/v1/reviews/{review_id}/decision ===")
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
    r = client.post(f"/api/v1/reviews/{review_id}/decision", json=decision_payload)
    assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
    print("  Accepted")

    # ── Wait for COMPLETED ────────────────────────────────────────────────
    print("  Polling for COMPLETED...")
    final = poll_case(case_id, "COMPLETED", timeout=15)
    assert final["review"]["status"] == "CLOSED", f"Review should be CLOSED, got {final['review']['status']}"
    print(f"  Final status: {final['workflow_status']}, review: {final['review']['status']}")

    # Check DECISION_RECEIVED and DECISION_APPLIED are in history
    event_types = [e["type"] for e in final["history"]]
    assert "DECISION_RECEIVED" in event_types, f"Missing DECISION_RECEIVED in {event_types}"
    assert "DECISION_APPLIED" in event_types, f"Missing DECISION_APPLIED in {event_types}"
    print(f"  History events: {event_types}")

    # ── Duplicate decision (should 409) ───────────────────────────────────
    print("\n=== Duplicate decision (expect 409) ===")
    r = client.post(f"/api/v1/reviews/{review_id}/decision", json=decision_payload)
    assert r.status_code == 409, f"Expected 409, got {r.status_code}: {r.text}"
    print(f"  Got {r.status_code} ✓")

    # ── Reprocess ─────────────────────────────────────────────────────────
    print(f"\n=== POST /api/v1/cases/{case_id}/reprocess ===")
    r = client.post(f"/api/v1/cases/{case_id}/reprocess")
    assert r.status_code == 202, f"Expected 202, got {r.status_code}: {r.text}"
    new_run_id = r.json()["run"]["run_id"]
    print(f"  New run_id={new_run_id}")

    # ── Wait for reprocessed case to reach AWAITING_HUMAN again ──────────
    print("  Polling for AWAITING_HUMAN after reprocess...")
    data = poll_case(case_id, "AWAITING_HUMAN", timeout=15)
    # The case's review should belong to the new run, not the old one
    assert data["review"]["run_id"] == new_run_id, (
        f"Review run_id mismatch: expected {new_run_id}, got {data['review']['run_id']}"
    )
    print(f"  Review run_id matches new run ✓")

    # ── List / filter ──────────────────────────────────────────────────────
    print("\n=== GET /api/v1/cases?workflow_status=AWAITING_HUMAN ===")
    r = client.get("/api/v1/cases?workflow_status=AWAITING_HUMAN")
    assert r.status_code == 200
    print(f"  {len(r.json())} case(s) AWAITING_HUMAN")

    # ── Stats ──────────────────────────────────────────────────────────────
    print("\n=== GET /api/v1/stats ===")
    r = client.get("/api/v1/stats")
    assert r.status_code == 200, r.text
    stats = r.json()
    print(f"  total_cases={stats['total_cases']}")
    print(f"  by_workflow={stats['by_workflow']}")
    # All enum values should be present even if 0
    from backend.schemas import WorkflowStatus, EmailCategory
    for s in WorkflowStatus:
        assert s.value in stats["by_workflow"], f"Missing {s.value} in by_workflow"
    for c in EmailCategory:
        assert c.value in stats["by_category"], f"Missing {c.value} in by_category"
    print("  All enum keys present ✓")

    # ── Document placeholder ───────────────────────────────────────────────
    print("\n=== GET /api/v1/documents/fake_id/content (expect 404) ===")
    r = client.get("/api/v1/documents/fake_id/content")
    assert r.status_code == 404
    print(f"  Got 404 ✓")

    # ── Duplicate POST /cases (expect 200) ────────────────────────────────
    print("\n=== Duplicate POST /api/v1/cases (expect 200) ===")
    r = client.post("/api/v1/cases", json=demo_email_payload)
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    print(f"  Got 200 ✓")

    print("\n[SUCCESS] All tests passed!")
