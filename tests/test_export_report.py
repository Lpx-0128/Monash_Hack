import json
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend import export_report

client = TestClient(app)


def test_export_report_module_single_and_bulk():
    mock_case = {
        "case_id": "email_demo_test",
        "schema_version": "2.1.2",
        "created_at": "2026-09-22T00:00:00Z",
        "completed_at": "2026-09-22T00:00:05Z",
        "workflow_status": "COMPLETED",
        "follow_up": "NONE",
        "email": {
            "from": "carrier@shipping.com",
            "subject": "SI and BL for Shipment #10492",
            "category": "BL_COMPARISON",
            "classified_by": "DETERMINISTIC",
            "classification_reason": "explicit subject match",
        },
        "machine_assessment": {
            "status": "OK",
            "review_reason": None,
            "has_defect": False,
            "defect_fields": [],
            "overall_confidence": 1.0,
            "explanation": "All 7 canonical shipping fields match verified document evidence exactly.",
        },
        "fields": [
            {
                "field": "container_count",
                "result": "MATCH",
                "not_comparable_cause": None,
                "compared_by": "DETERMINISTIC",
                "confidence": 1.0,
                "explanation": "SI and Draft BL match exactly for container_count with verified document evidence.",
                "si": {
                    "raw": "1 x 40HC",
                    "normalized": 1,
                    "resolved_by": "DETERMINISTIC",
                    "value_origin": "DOCUMENT_EXTRACTED",
                    "grounded": True,
                    "evidence": [{"source_text": "1x40HC"}],
                },
                "bl": {
                    "raw": "1 x 40HC",
                    "normalized": 1,
                    "resolved_by": "DETERMINISTIC",
                    "value_origin": "DOCUMENT_EXTRACTED",
                    "grounded": True,
                    "evidence": [{"source_text": "1x40HC"}],
                },
            }
        ],
        "metrics": {"ai_calls": 0, "ai_assisted_fields": 0, "processing_ms": 120},
    }

    rep = export_report.generate_case_report(mock_case)
    assert rep["case_id"] == "email_demo_test"
    assert rep["machine_assessment"]["overall_confidence"] == 1.0
    assert len(rep["fields"]) == 1
    assert rep["fields"][0]["si"]["evidence_quote"] == "1x40HC"

    bulk = export_report.generate_bulk_report([mock_case])
    assert len(bulk) == 1

    csv_text = export_report.export_report_csv(bulk)
    assert "Case ID,Email Subject,Email Sender" in csv_text
    assert "email_demo_test" in csv_text
    assert "container_count" in csv_text
    assert "100%" in csv_text

    json_text = export_report.export_report_json(bulk)
    parsed = json.loads(json_text)
    assert parsed[0]["case_id"] == "email_demo_test"


from tests.conftest import DEMO_MATCH, DEMO_MISSING_WEIGHT
from tests.helpers import create_and_wait


def test_export_report_endpoints(client):
    # Ingest demo cases
    create_and_wait(client, DEMO_MATCH, "COMPLETED")

    # Test bulk export JSON
    res_json = client.get("/api/v1/export/report?format=json")
    assert res_json.status_code == 200
    assert res_json.headers["content-type"] == "application/json"
    data = res_json.json()
    assert isinstance(data, list)
    assert len(data) > 0

    # Test bulk export CSV
    res_csv = client.get("/api/v1/export/report?format=csv")
    assert res_csv.status_code == 200
    assert "text/csv" in res_csv.headers["content-type"]
    assert "Case ID" in res_csv.text

    # Test bulk export only mismatches
    res_mismatch = client.get("/api/v1/export/report?format=json&only_mismatches=true")
    assert res_mismatch.status_code == 200
    m_data = res_mismatch.json()
    assert isinstance(m_data, list)

    # Test single case export
    first_case_id = data[0]["case_id"]
    res_single_json = client.get(f"/api/v1/cases/{first_case_id}/export?format=json")
    assert res_single_json.status_code == 200
    s_data = res_single_json.json()
    assert s_data["case_id"] == first_case_id

    res_single_csv = client.get(f"/api/v1/cases/{first_case_id}/export?format=csv")
    assert res_single_csv.status_code == 200
    assert "text/csv" in res_single_csv.headers["content-type"]
    assert first_case_id in res_single_csv.text

    # Test EVAL scope export
    eval_res = client.get("/api/v1/export/report?format=json", headers={"X-Run-Kind": "EVAL"})
    assert eval_res.status_code == 200
    assert isinstance(eval_res.json(), list)

