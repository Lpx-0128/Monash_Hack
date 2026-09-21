"""Tests for mock email composer endpoint (POST /api/v1/inbox/compose)."""

import io
from fastapi.testclient import TestClient
from backend.main import app
from backend.database import SessionLocal
from backend import crud, schemas
from backend.worker_loop import _process_job


def test_compose_mock_bl_comparison_email():
    """Operator / judge composes a mock BL comparison email with SI and BL attachments."""
    client = TestClient(app)

    si_content = b"""SHIPPING INSTRUCTION
SHIPPER: ACME LOGISTICS LTD
CONSIGNEE: GLOBAL TRADING CORP
NOTIFY PARTY: GLOBAL TRADING CORP
PORT OF LOADING: SHANGHAI, CHINA (CNSHA)
PORT OF DISCHARGE: ROTTERDAM, NETHERLANDS (NLRTM)
CONTAINER COUNT: 2 x 40'HC
GROSS WEIGHT: 25000 KG
"""

    bl_content = b"""DRAFT BILL OF LADING
SHIPPER: ACME LOGISTICS LTD
CONSIGNEE: GLOBAL TRADING CORP
NOTIFY PARTY: GLOBAL TRADING CORP
PORT OF LOADING: SHANGHAI, CHINA (CNSHA)
PORT OF DISCHARGE: ROTTERDAM, NETHERLANDS (NLRTM)
CONTAINER COUNT: 2 x 40'HC
GROSS WEIGHT: 25000 KG
"""

    files = [
        ("files", ("mock_shipment_SI.txt", io.BytesIO(si_content), "text/plain")),
        ("files", ("mock_shipment_BL.txt", io.BytesIO(bl_content), "text/plain")),
    ]
    data = {
        "from_address": "shipping-ops@oceanlogistics.com",
        "subject": "TO CHECK DOCS - VOYAGE 2026 - ACME / GLOBAL TRADING",
        "body": "Hi Documentation Team,\n\nPlease find attached the SI and draft BL for checking.\nBest regards,\nOps",
    }

    resp = client.post("/api/v1/inbox/compose", data=data, files=files)
    assert resp.status_code == 202
    created = resp.json()
    case_id = created["case_id"]
    assert case_id.startswith("email_custom_")
    assert created["run"]["kind"] == "DEMO"
    assert created["workflow_status"] == "PROCESSING"

    # Process job via worker
    db = SessionLocal()
    try:
        jobs = crud.get_pending_jobs(db)
        for job in jobs:
            if job.case_id == case_id:
                _process_job(job)
                db.commit()
    finally:
        db.close()

    # Query the case after processing
    resp = client.get(f"/api/v1/cases/{case_id}")
    assert resp.status_code == 200
    case = resp.json()

    assert case["email"]["category"] == "BL_COMPARISON"
    assert case["workflow_status"] == "COMPLETED"
    assert case["machine_assessment"]["status"] == "OK"
    assert case["machine_assessment"]["has_defect"] is False
    assert len(case["fields"]) == 7
    for f in case["fields"]:
        assert f["result"] == "MATCH"

    # Verify attachment content streaming
    doc_id = case["documents"][0]["document_id"]
    doc_resp = client.get(f"/api/v1/documents/{doc_id}/content")
    assert doc_resp.status_code == 200
    assert len(doc_resp.content) > 0


def test_compose_mock_spam_email_is_filtered():
    """Spam email is classified into SPAM and settled without SI/BL comparison."""
    client = TestClient(app)

    data = {
        "from_address": "promotions@unsolicited-marketing.com",
        "subject": "Exclusive Discount Offer on Office Supplies - Limited Time",
        "body": "Dear valued customer, click here to claim your 50% discount on printing paper and toner cartridges.",
    }

    resp = client.post("/api/v1/inbox/compose", data=data)
    assert resp.status_code == 202
    created = resp.json()
    case_id = created["case_id"]

    db = SessionLocal()
    try:
        jobs = crud.get_pending_jobs(db)
        for job in jobs:
            if job.case_id == case_id:
                _process_job(job)
                db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/v1/cases/{case_id}")
    assert resp.status_code == 200
    case = resp.json()

    assert case["email"]["category"] == "SPAM"
    assert case["workflow_status"] == "COMPLETED"
    assert case["review"] is None
    # No comparison fields for non-BL emails
    assert len(case["fields"]) == 0


def test_compose_validation_missing_fields():
    """Ensure empty sender or subject returns HTTP 422."""
    client = TestClient(app)

    resp = client.post("/api/v1/inbox/compose", data={"from_address": "", "subject": "Test", "body": "Hello"})
    assert resp.status_code == 422

    resp = client.post("/api/v1/inbox/compose", data={"from_address": "test@test.com", "subject": "   ", "body": "Hello"})
    assert resp.status_code == 422


def test_compose_incoming_case_with_human_value_decision():
    """Human operator decides / overrides a value on an incoming case requiring review."""
    client = TestClient(app)

    si_content = b"""SHIPPING INSTRUCTION
SHIPPER: GLOBAL LOGISTICS INC
CONSIGNEE: ORIENT TRADERS
NOTIFY PARTY: ORIENT TRADERS
PORT OF LOADING: SINGAPORE (SGSIN)
PORT OF DISCHARGE: BUSAN, KOREA (KRPUS)
CONTAINER COUNT: 1 x 40'HC
GROSS WEIGHT: 22000 KG
"""

    # Draft BL has missing / unreadable gross weight
    bl_content = b"""DRAFT BILL OF LADING
SHIPPER: GLOBAL LOGISTICS INC
CONSIGNEE: ORIENT TRADERS
NOTIFY PARTY: ORIENT TRADERS
PORT OF LOADING: SINGAPORE (SGSIN)
PORT OF DISCHARGE: BUSAN, KOREA (KRPUS)
CONTAINER COUNT: 1 x 40'HC
GROSS WEIGHT: PENDING WEIGHBRIDGE
"""

    files = [
        ("files", ("si_input.txt", io.BytesIO(si_content), "text/plain")),
        ("files", ("bl_draft.txt", io.BytesIO(bl_content), "text/plain")),
    ]
    data = {
        "from_address": "ops@orient-shipping.com",
        "subject": "COMPARE SI AND DRAFT BL - BOOKING #OR-88219",
        "body": "Please compare the attached SI and draft BL for checking.",
    }

    resp = client.post("/api/v1/inbox/compose", data=data, files=files)
    assert resp.status_code == 202
    created = resp.json()
    case_id = created["case_id"]

    # Process first pass
    db = SessionLocal()
    try:
        jobs = crud.get_pending_jobs(db)
        for job in jobs:
            if job.case_id == case_id:
                _process_job(job)
                db.commit()
    finally:
        db.close()

    # Case should enter AWAITING_HUMAN with an OPEN review
    resp = client.get(f"/api/v1/cases/{case_id}")
    assert resp.status_code == 200
    case = resp.json()
    assert case["workflow_status"] == "AWAITING_HUMAN"
    assert case["review"] is not None
    assert case["review"]["status"] == "OPEN"
    review_id = case["review"]["review_id"]
    run_id = case["run"]["run_id"]

    # Human intervention: Operator decides the gross weight value (22000 KG)
    decision_payload = {
        "review_id": review_id,
        "run_id": run_id,
        "action": "PROVIDE_VALUE",
        "actor_id": "human_operator_ahmad",
        "channel": "DASHBOARD",
        "field": "gross_weight_kg",
        "side": "BL",
        "value": 22000,
        "override_confirmation": {
            "review_id": review_id,
            "run_id": run_id,
            "field": "gross_weight_kg",
            "side": "BL",
            "proposed_value": 22000,
            "confirmed": True,
        },
        "user_message": "Operator verified weighbridge ticket: 22,000 KG confirmed.",
    }

    decision_resp = client.post(f"/api/v1/reviews/{review_id}/decision", json=decision_payload)
    assert decision_resp.status_code == 202
    assert decision_resp.json()["workflow_status"] == "PROCESSING"

    # Process APPLY_DECISION job
    db = SessionLocal()
    try:
        jobs = crud.get_pending_jobs(db)
        for job in jobs:
            if job.case_id == case_id:
                _process_job(job)
                db.commit()
    finally:
        db.close()

    # Verify that the case is now COMPLETED and the human decision is durably stored
    after_resp = client.get(f"/api/v1/cases/{case_id}")
    assert after_resp.status_code == 200
    updated_case = after_resp.json()

    assert updated_case["workflow_status"] == "COMPLETED"
    assert updated_case["review"]["status"] == "CLOSED"
    assert updated_case["review"]["close_reason"] == "DECISION_ACCEPTED"
    assert updated_case["resolution"] is not None
    assert updated_case["resolution"]["actor_id"] == "human_operator_ahmad"
    assert updated_case["resolution"]["value_source"] == "MANUAL_OVERRIDE"

    # Verify updated field outcome
    gw = next(f for f in updated_case["fields"] if f["field"] == "gross_weight_kg")
    assert gw["bl"]["normalized"] == 22000
    assert gw["bl"]["resolved_by"] == "HUMAN"
    assert gw["bl"]["value_origin"] == "MANUAL_OVERRIDE"
    assert gw["result"] == "MATCH"

    # Verify history event log
    history_types = [h["type"] for h in updated_case["history"]]
    assert "DECISION_RECEIVED" in history_types
    assert "DECISION_APPLIED" in history_types


def test_compose_incoming_case_with_human_acknowledge_close():
    """Human operator closes / acknowledges external blockage on an unresolvable case."""
    client = TestClient(app)

    si_content = b"""SHIPPING INSTRUCTION
SHIPPER: PACIFIC CARGO CORP
CONSIGNEE: ASIA IMPORTS LTD
NOTIFY PARTY: ASIA IMPORTS LTD
PORT OF LOADING: SHANGHAI (CNSHA)
PORT OF DISCHARGE: MANILA (PHMNL)
CONTAINER COUNT: 3 x 20'GP
GROSS WEIGHT: 45000 KG
"""

    bl_content = b"""DRAFT BILL OF LADING
SHIPPER: PACIFIC CARGO CORP
CONSIGNEE: ASIA IMPORTS LTD
NOTIFY PARTY: ASIA IMPORTS LTD
PORT OF LOADING: SHANGHAI (CNSHA)
PORT OF DISCHARGE: MANILA (PHMNL)
CONTAINER COUNT: 3 x 20'GP
GROSS WEIGHT: [BLURRED / UNREADABLE SCANNED TEXT]
"""

    files = [
        ("files", ("si_input.txt", io.BytesIO(si_content), "text/plain")),
        ("files", ("bl_draft.txt", io.BytesIO(bl_content), "text/plain")),
    ]
    data = {
        "from_address": "ops@pacific-cargo.com",
        "subject": "COMPARE SI AND DRAFT BL - VOYAGE 409",
        "body": "Please compare attached SI and Draft BL.",
    }

    resp = client.post("/api/v1/inbox/compose", data=data, files=files)
    assert resp.status_code == 202
    case_id = resp.json()["case_id"]

    db = SessionLocal()
    try:
        jobs = crud.get_pending_jobs(db)
        for job in jobs:
            if job.case_id == case_id:
                _process_job(job)
                db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/v1/cases/{case_id}")
    case = resp.json()
    assert case["workflow_status"] == "AWAITING_HUMAN"
    review_id = case["review"]["review_id"]
    run_id = case["run"]["run_id"]

    # Human intervention: Operator acknowledges external block / closes
    ack_payload = {
        "review_id": review_id,
        "run_id": run_id,
        "action": "ACKNOWLEDGE",
        "actor_id": "operator_close_test",
        "channel": "DASHBOARD",
        "user_message": "Document weight unreadable. Requested replacement scan from shipper.",
    }

    ack_resp = client.post(f"/api/v1/reviews/{review_id}/decision", json=ack_payload)
    assert ack_resp.status_code == 202

    db = SessionLocal()
    try:
        jobs = crud.get_pending_jobs(db)
        for job in jobs:
            if job.case_id == case_id:
                _process_job(job)
                db.commit()
    finally:
        db.close()

    resp = client.get(f"/api/v1/cases/{case_id}")
    updated = resp.json()
    assert updated["workflow_status"] == "BLOCKED_EXTERNAL"
    assert updated["follow_up"] == "AWAIT_EXTERNAL"
    assert updated["review"]["status"] == "CLOSED"
    assert updated["review"]["close_reason"] == "DECISION_ACCEPTED"


