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
