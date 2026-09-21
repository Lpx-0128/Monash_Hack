"""The automated pass, driven through the real backend and worker."""

import pytest

from tests.conftest import (
    DEMO_CORRUPT,
    DEMO_DOCUMENT_CHOICE,
    DEMO_INVOICE,
    DEMO_MATCH,
    DEMO_MISMATCH,
    DEMO_MISSING_WEIGHT,
    DEMO_NO_ATTACHMENTS,
    DEMO_OFFICE,
    DEMO_PDF,
    DEMO_SCANNED,
    DEMO_WRONG_DOC,
)
from tests.helpers import create_and_wait

CANONICAL_FIELDS = ["shipper", "consignee", "notify_party", "port_of_loading",
                    "port_of_discharge", "container_count", "gross_weight_kg"]


def test_a_clean_comparison_completes_automatically(client):
    case = create_and_wait(client, DEMO_MATCH, "COMPLETED")

    assert case["email"]["category"] == "BL_COMPARISON"
    assert case["machine_assessment"]["status"] == "OK"
    assert case["machine_assessment"]["has_defect"] is False
    assert case["machine_assessment"]["defect_fields"] == []
    assert case["machine_assessment"]["review_reason"] is None
    assert case["review"] is None
    assert case["follow_up"] == "NONE"
    assert case["completed_at"] is not None

    # Invariant 7: exactly seven unique canonical fields.
    fields = [f["field"] for f in case["fields"]]
    assert fields == CANONICAL_FIELDS
    assert all(f["result"] == "MATCH" for f in case["fields"])


def test_extracted_values_carry_real_evidence(client):
    """Values are grounded in the actual document, not asserted."""
    case = create_and_wait(client, DEMO_MATCH, "COMPLETED")
    documents = {d["document_id"] for d in case["documents"]}

    for comparison in case["fields"]:
        for side in ("si", "bl"):
            value = comparison[side]
            assert value is not None, f"{comparison['field']} {side}"
            assert value["raw"]
            assert value["normalized"] is not None
            assert value["grounded"] is True
            assert value["resolved_by"] == "DETERMINISTIC"
            assert value["value_origin"] == "DOCUMENT_EXTRACTED"
            assert value["evidence"], f"{comparison['field']} {side} has no evidence"
            for reference in value["evidence"]:
                assert reference["document_id"] in documents
                assert reference["locator"]["kind"] in (
                    "text_range", "pdf_page", "docx_paragraph", "docx_table_cell", "sheet_cell"
                )
                assert reference["source_text"]


def test_a_real_difference_is_reported_as_a_mismatch(client):
    case = create_and_wait(client, DEMO_MISMATCH, "COMPLETED")

    assert case["machine_assessment"]["status"] == "MISMATCH"
    assert case["machine_assessment"]["has_defect"] is True
    assert case["machine_assessment"]["defect_fields"] == ["consignee"]
    assert case["machine_assessment"]["review_reason"] is None
    assert case["follow_up"] == "CORRECTION_REQUIRED"

    consignee = next(f for f in case["fields"] if f["field"] == "consignee")
    assert consignee["result"] == "MISMATCH"
    # The two sides genuinely differ and both are quoted.
    assert consignee["si"]["normalized"] != consignee["bl"]["normalized"]
    assert consignee["si"]["evidence"] and consignee["bl"]["evidence"]


def test_a_missing_value_opens_a_targeted_question(client):
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")

    assert case["machine_assessment"]["status"] == "NEEDS_REVIEW"
    assert case["machine_assessment"]["review_reason"] == "missing_value"
    assert case["machine_assessment"]["defect_fields"] == []
    assert case["completed_at"] is None

    review = case["review"]
    assert review["status"] == "OPEN"
    assert review["scope"] == "FIELD"
    assert review["ui_mode"] == "VALUE_INPUT"
    assert review["field"] == "gross_weight_kg"
    assert review["side"] == "BL"
    assert review["target_role"] is None
    assert set(review["allowed_actions"]) == {"PROVIDE_VALUE", "ACKNOWLEDGE"}
    assert review["closed_at"] is None and review["close_reason"] is None
    assert review["source_documents"]
    # The question distinguishes absent from uninterpretable.
    assert "N/A" in review["context_summary"] or "no value" in review["context_summary"]


def test_a_missing_attachment_blocks_externally(client):
    case = create_and_wait(client, DEMO_NO_ATTACHMENTS, "BLOCKED_EXTERNAL")

    assert case["email"]["category"] == "BL_COMPARISON"   # NOT_READY is not a bypass
    assert case["machine_assessment"]["status"] == "NEEDS_REVIEW"
    assert case["machine_assessment"]["review_reason"] == "missing_attachment"
    assert case["follow_up"] == "AWAIT_EXTERNAL"
    assert case["review"]["ui_mode"] == "ACKNOWLEDGE"
    assert case["review"]["allowed_actions"] == ["ACKNOWLEDGE"]
    assert case["review"]["field"] is None
    assert case["review"]["side"] is None
    assert case["review"]["target_role"] is None
    # Settled BL cases still carry all seven fields.
    assert [f["field"] for f in case["fields"]] == CANONICAL_FIELDS


def test_a_wrong_document_type_is_reported_as_such(client):
    case = create_and_wait(client, DEMO_WRONG_DOC, "BLOCKED_EXTERNAL")
    assert case["machine_assessment"]["review_reason"] == "wrong_doc_type"
    roles = {d["filename"]: d["role"] for d in case["documents"]}
    assert roles["demo_wrongdoc_SI.txt"] == "SI"
    # The packing list is not a BL, whatever the filename suggests.
    assert roles["demo_wrongdoc_BL.txt"] != "BL"


def test_a_scanned_document_is_reported_as_unreadable(client):
    case = create_and_wait(client, DEMO_SCANNED, "BLOCKED_EXTERNAL")
    assert case["machine_assessment"]["review_reason"] == "unreadable"
    statuses = {d["filename"]: d["parse_status"] for d in case["documents"]}
    assert statuses["demo_scan_BL.pdf"] == "UNREADABLE"
    assert statuses["demo_scan_SI.pdf"] == "OK"
    # The review says the document is a scan, and does not claim OCR was tried.
    summary = case["review"]["context_summary"].lower()
    assert "scan" in summary or "text layer" in summary
    assert "ocr" not in summary or "not enabled" in summary


def test_a_corrupt_document_is_a_source_issue_not_a_failure(client):
    case = create_and_wait(client, DEMO_CORRUPT, "BLOCKED_EXTERNAL")
    assert case["workflow_status"] != "FAILED"
    assert case["failure"] is None
    assert case["machine_assessment"]["review_reason"] == "unreadable"


def test_two_plausible_drafts_produce_a_document_choice(client):
    case = create_and_wait(client, DEMO_DOCUMENT_CHOICE, "AWAITING_HUMAN")
    review = case["review"]

    assert review["scope"] == "DOCUMENT"
    assert review["ui_mode"] == "CHOICE"
    assert review["target_role"] == "BL"
    assert review["field"] is None and review["side"] is None
    assert review["allowed_actions"] == ["SELECT_OPTION"]

    options = review["options"]
    escapes = [o for o in options if o["option_id"] == "NONE_OF_THESE"]
    assert len(escapes) == 1 and escapes[0]["kind"] == "ESCAPE"
    documents = [o for o in options if o["kind"] == "DOCUMENT"]
    assert len(documents) == 2
    assert len({o["option_id"] for o in options}) == len(options)


def test_a_non_bl_case_settles_with_no_fields_and_no_review(client):
    case = create_and_wait(client, DEMO_INVOICE, "COMPLETED")
    assert case["email"]["category"] == "INVOICE_QUERY"
    assert case["machine_assessment"]["status"] == "OK"
    assert case["fields"] == []
    assert case["review"] is None
    assert case["machine_assessment"]["defect_fields"] == []


@pytest.mark.parametrize("email_id", [DEMO_PDF, DEMO_OFFICE])
def test_pdf_and_office_formats_complete_through_the_backend(client, email_id):
    """Each required format is exercised end to end, not only in unit tests."""
    case = create_and_wait(client, email_id, "COMPLETED")
    assert case["machine_assessment"]["status"] == "OK"
    assert len(case["fields"]) == 7
    kinds = {
        reference["locator"]["kind"]
        for comparison in case["fields"]
        for side in ("si", "bl")
        for reference in comparison[side]["evidence"]
    }
    assert kinds  # every value is anchored to a real location


def test_the_case_records_reproducible_run_identity(client):
    case = create_and_wait(client, DEMO_MATCH, "COMPLETED")
    run = case["run"]
    assert run["input_version"].startswith("iv1_")
    assert run["config_version"].startswith("person-a-v1+")
    assert run["kind"] == "DEMO"
    # Unknown receipt time stays null, in every workflow state.
    assert case["email"]["received_at"] is None
    assert case["email"]["classified_by"] in ("DETERMINISTIC", "AI")
    assert case["metrics"]["est_ai_cost_usd"] is None    # unknown, not a guessed zero
    assert case["metrics"]["processing_ms"] is not None


def test_history_records_what_actually_happened(client):
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    types = [event["type"] for event in case["history"]]
    assert "CASE_CREATED" in types
    assert "EMAIL_CLASSIFIED" in types
    assert "DOCUMENT_PARSED" in types
    assert "COMPARISON_COMPLETED" in types
    assert "REVIEW_CREATED" in types


def test_an_unregistered_email_id_creates_nothing(client):
    response = client.post("/api/v1/cases", json={"email_id": "email_does_not_exist"})
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert client.get("/api/v1/cases/email_does_not_exist").status_code == 404


def test_reprocess_produces_a_new_run_with_a_stable_created_at(client):
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    original_run = case["run"]["run_id"]
    created_at = case["created_at"]

    response = client.post(f"/api/v1/cases/{case['case_id']}/reprocess")
    assert response.status_code == 202
    new_run = response.json()["run"]["run_id"]
    assert new_run != original_run

    from tests.helpers import poll_case

    reprocessed = poll_case(client, case["case_id"], "AWAITING_HUMAN")
    assert reprocessed["run"]["run_id"] == new_run
    assert reprocessed["review"]["run_id"] == new_run
    assert reprocessed["created_at"] == created_at       # stable across reprocess
    assert reprocessed["email"]["received_at"] is None
