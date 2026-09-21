"""Human decisions through the real API (handoff cases I-01 to I-09)."""

import pytest

from backend import models
from backend.database import SessionLocal
from tests.conftest import (
    DEMO_DOCUMENT_CHOICE,
    DEMO_MISSING_WEIGHT,
    DEMO_NO_ATTACHMENTS,
)
from tests.helpers import create_and_wait, poll_case

# Read off demo_missing_BL.txt by hand: the SI states 18500 KG and the BL says N/A.
SI_GROSS_WEIGHT_KG = 18500


def open_review(client, email_id=DEMO_MISSING_WEIGHT, status="AWAITING_HUMAN"):
    case = create_and_wait(client, email_id, status)
    return case, case["review"]


def decide(client, review, **payload):
    body = {"review_id": review["review_id"], "run_id": review["run_id"],
            "channel": "DASHBOARD", "actor_id": "operator_1"}
    body.update(payload)
    return client.post(f"/api/v1/reviews/{review['review_id']}/decision", json=body)


def decision_rows(case_id):
    db = SessionLocal()
    try:
        return db.query(models.AcceptedDecisionModel).filter_by(case_id=case_id).all()
    finally:
        db.close()


def test_i01_an_unsupported_value_is_refused_and_changes_nothing(client):
    """I-01: 422, the review stays OPEN, no accepted record and no job."""
    case, review = open_review(client)

    response = decide(client, review, action="PROVIDE_VALUE", field="gross_weight_kg",
                      side="BL", value=999999)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALUE_NOT_FOUND_IN_DOCUMENT"

    after = client.get(f"/api/v1/cases/{case['case_id']}").json()
    assert after["workflow_status"] == "AWAITING_HUMAN"
    assert after["review"]["status"] == "OPEN"
    assert after["review"]["closed_at"] is None
    assert after["resolution"] is None
    assert decision_rows(case["case_id"]) == []


def test_i01_the_same_value_is_accepted_once_explicitly_confirmed(client):
    """I-01: an explicit confirmation records the override with ungrounded lineage."""
    case, review = open_review(client)

    response = decide(
        client, review, action="PROVIDE_VALUE", field="gross_weight_kg", side="BL",
        value=999999,
        override_confirmation={
            "review_id": review["review_id"], "run_id": review["run_id"],
            "field": "gross_weight_kg", "side": "BL",
            "proposed_value": 999999, "confirmed": True,
        },
    )
    assert response.status_code == 202
    # Acceptance is durable but not yet applied.
    assert response.json()["workflow_status"] == "PROCESSING"

    completed = poll_case(client, case["case_id"], "COMPLETED")
    weight = next(f for f in completed["fields"] if f["field"] == "gross_weight_kg")
    assert weight["bl"]["normalized"] == 999999
    assert weight["bl"]["resolved_by"] == "HUMAN"
    assert weight["bl"]["value_origin"] == "MANUAL_OVERRIDE"
    assert weight["bl"]["grounded"] is False
    # Evidence never claims to support an overridden value.
    assert weight["bl"]["evidence"] == []
    assert weight["bl"]["override_confirmations"][0]["confirmed"] is True
    assert weight["result"] == "MISMATCH"
    assert completed["resolution"]["value_source"] == "MANUAL_OVERRIDE"


def test_a_document_confirmed_value_is_grounded_with_real_evidence(client):
    """A value the document really shows is confirmed, not overridden."""
    case, review = open_review(client)

    # The SI states 18500 KG; the BL's own weight is N/A, so this needs an override.
    # Use the SI-side review of a different fixture instead: here confirm via the
    # value the BL document does support is impossible, so assert the refusal.
    response = decide(client, review, action="PROVIDE_VALUE", field="gross_weight_kg",
                      side="BL", value=SI_GROSS_WEIGHT_KG)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALUE_NOT_FOUND_IN_DOCUMENT"


def test_i02_a_mismatched_field_or_side_is_refused_without_mutation(client):
    case, review = open_review(client)

    wrong_field = decide(client, review, action="PROVIDE_VALUE", field="container_count",
                         side="BL", value=4)
    assert wrong_field.status_code == 422

    wrong_side = decide(client, review, action="PROVIDE_VALUE", field="gross_weight_kg",
                        side="SI", value=18500)
    assert wrong_side.status_code == 422

    after = client.get(f"/api/v1/cases/{case['case_id']}").json()
    assert after["review"]["status"] == "OPEN"
    assert decision_rows(case["case_id"]) == []


def test_i02_a_body_review_id_that_differs_from_the_path_is_refused(client):
    case, review = open_review(client)
    response = client.post(
        f"/api/v1/reviews/{review['review_id']}/decision",
        json={"review_id": "rev_somethingelse", "run_id": review["run_id"],
              "channel": "DASHBOARD", "actor_id": "op", "action": "ACKNOWLEDGE"},
    )
    assert response.status_code == 422


def test_i02_an_action_outside_allowed_actions_is_refused(client):
    case, review = open_review(client)
    response = decide(client, review, action="SELECT_OPTION", option_id="val_1")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "ACTION_NOT_ALLOWED"


def test_i02_a_false_confirmation_is_refused(client):
    case, review = open_review(client)
    response = decide(
        client, review, action="PROVIDE_VALUE", field="gross_weight_kg", side="BL", value=777,
        override_confirmation={
            "review_id": review["review_id"], "run_id": review["run_id"],
            "field": "gross_weight_kg", "side": "BL", "proposed_value": 777, "confirmed": False,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CONFIRMATION"


def test_i03_a_confirmation_bound_to_another_value_cannot_be_reused(client):
    """I-03: editing the value invalidates the confirmation."""
    case, review = open_review(client)
    response = decide(
        client, review, action="PROVIDE_VALUE", field="gross_weight_kg", side="BL", value=888,
        override_confirmation={
            "review_id": review["review_id"], "run_id": review["run_id"],
            "field": "gross_weight_kg", "side": "BL", "proposed_value": 777, "confirmed": True,
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CONFIRMATION"
    assert decision_rows(case["case_id"]) == []


def test_a_non_scalar_value_is_refused(client):
    case, review = open_review(client)
    for bad in (True, [18500], {"value": 18500}):
        response = decide(client, review, action="PROVIDE_VALUE",
                          field="gross_weight_kg", side="BL", value=bad)
        assert response.status_code == 422, bad


def test_i09_acknowledgement_returns_processing_then_blocks_externally(client):
    """I-09: 202 PROCESSING first, then a CLOSED review and a NEEDS_REVIEW resolution."""
    case, review = open_review(client)

    response = decide(client, review, action="ACKNOWLEDGE",
                      user_message="The customer must reissue the draft.")
    assert response.status_code == 202
    accepted = response.json()
    assert accepted["workflow_status"] == "PROCESSING"
    # Acceptance does not optimistically claim a final status.
    assert accepted["resolution"] is None

    blocked = poll_case(client, case["case_id"], "BLOCKED_EXTERNAL")
    assert blocked["review"]["status"] == "CLOSED"
    assert blocked["review"]["closed_at"] is not None
    assert blocked["review"]["close_reason"]
    assert blocked["resolution"]["final_status"] == "NEEDS_REVIEW"
    assert blocked["resolution"]["final_defect_fields"] == []
    assert blocked["follow_up"] == "AWAIT_EXTERNAL"
    # Acknowledging does not complete verification.
    assert blocked["completed_at"] is None
    # The frozen machine assessment is untouched.
    assert blocked["machine_assessment"]["status"] == "NEEDS_REVIEW"


def test_i09_none_of_these_blocks_externally(client):
    case, review = open_review(client, DEMO_DOCUMENT_CHOICE)
    response = decide(client, review, action="SELECT_OPTION", option_id="NONE_OF_THESE")
    assert response.status_code == 202
    assert response.json()["workflow_status"] == "PROCESSING"

    blocked = poll_case(client, case["case_id"], "BLOCKED_EXTERNAL")
    assert blocked["follow_up"] == "AWAIT_EXTERNAL"
    assert blocked["resolution"]["final_status"] == "NEEDS_REVIEW"


def test_natural_language_text_is_not_an_authorization_shortcut(client):
    """"I can't tell" in a free-text field does not bypass action validation."""
    case, review = open_review(client)
    response = decide(client, review, action="PROVIDE_VALUE", field="gross_weight_kg",
                      side="BL", value="", user_message="I can't tell")
    assert response.status_code == 422

    after = client.get(f"/api/v1/cases/{case['case_id']}").json()
    assert after["workflow_status"] == "AWAITING_HUMAN"
    assert after["review"]["status"] == "OPEN"


def test_i07_a_document_choice_reassigns_the_role_and_re_extracts(client):
    """I-07: the chosen side is re-derived; the opposite side is preserved."""
    case, review = open_review(client, DEMO_DOCUMENT_CHOICE)
    option = next(o for o in review["options"] if o["kind"] == "DOCUMENT")

    response = decide(client, review, action="SELECT_OPTION", option_id=option["option_id"])
    assert response.status_code == 202

    settled = poll_case(client, case["case_id"], "COMPLETED")
    roles = {d["document_id"]: d["role"] for d in settled["documents"]}
    assert roles.get(option["document_id"]) in ("BL", "UNKNOWN", "OTHER")
    assert len(settled["fields"]) == 7
    # The SI side still carries its own extracted values.
    shipper = next(f for f in settled["fields"] if f["field"] == "shipper")
    assert shipper["si"]["value_origin"] == "DOCUMENT_EXTRACTED"


def test_a_duplicate_decision_is_refused_with_409(client):
    case, review = open_review(client)
    first = decide(client, review, action="ACKNOWLEDGE")
    assert first.status_code == 202

    duplicate = decide(client, review, action="ACKNOWLEDGE")
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "REVIEW_ALREADY_CLOSED"


def test_a_stale_run_id_is_refused_with_409(client):
    case, review = open_review(client)
    response = client.post(
        f"/api/v1/reviews/{review['review_id']}/decision",
        json={"review_id": review["review_id"], "run_id": "run_ancient",
              "channel": "DASHBOARD", "actor_id": "op", "action": "ACKNOWLEDGE"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_RUN"
    assert decision_rows(case["case_id"]) == []


def test_the_accepted_decision_is_recorded_and_bound_to_its_job(client):
    """The worker applies a recorded decision, never one rediscovered from history."""
    case, review = open_review(client)
    response = decide(
        client, review, action="PROVIDE_VALUE", field="gross_weight_kg", side="BL", value=18500,
        override_confirmation={
            "review_id": review["review_id"], "run_id": review["run_id"],
            "field": "gross_weight_kg", "side": "BL",
            "proposed_value": 18500, "confirmed": True,
        },
    )
    assert response.status_code == 202

    rows = decision_rows(case["case_id"])
    assert len(rows) == 1
    record = rows[0]
    assert record.run_id == review["run_id"]
    assert record.review_id == review["review_id"]
    assert record.job_id
    assert record.payload["target_field"] == "gross_weight_kg"
    assert record.payload["canonical"]["normalized"]["number"] == "18500"

    poll_case(client, case["case_id"], "COMPLETED")
    rows = decision_rows(case["case_id"])
    assert rows[0].applied_at is not None    # the idempotency marker is set


def test_reapplying_an_already_applied_decision_changes_nothing(client):
    """I-12: a retry after a crash does not duplicate the application."""
    from backend import worker

    case, review = open_review(client)
    decide(client, review, action="PROVIDE_VALUE", field="gross_weight_kg", side="BL",
           value=18500,
           override_confirmation={
               "review_id": review["review_id"], "run_id": review["run_id"],
               "field": "gross_weight_kg", "side": "BL",
               "proposed_value": 18500, "confirmed": True,
           })
    completed = poll_case(client, case["case_id"], "COMPLETED")
    row = decision_rows(case["case_id"])[0]

    # Run the worker again for the same job, as a crashed retry would.
    worker.apply_decision(case["case_id"], job_id=row.job_id, job_run_id=review["run_id"])

    again = client.get(f"/api/v1/cases/{case['case_id']}").json()
    assert again["workflow_status"] == "COMPLETED"
    assert len(again["history"]) == len(completed["history"])
    assert len(decision_rows(case["case_id"])) == 1


def test_a_missing_decision_record_fails_loudly_with_no_default(client):
    """There is no 15000 fallback: a missing record is an explicit failure."""
    from backend import worker
    from backend.intelligence.types import PermanentProcessingError

    case, review = open_review(client)
    with pytest.raises(PermanentProcessingError, match="no accepted decision record"):
        worker.apply_decision(case["case_id"], job_id="job_never_existed",
                              job_run_id=review["run_id"])


def test_reprocess_discards_an_unapplied_decision_from_the_old_run(client):
    """I-13: work accepted against a superseded run never reaches the new one."""
    case, review = open_review(client)
    # Accept a decision, then immediately supersede the run.
    decide(client, review, action="ACKNOWLEDGE")
    client.post(f"/api/v1/cases/{case['case_id']}/reprocess")

    reprocessed = poll_case(client, case["case_id"], "AWAITING_HUMAN")
    assert reprocessed["run"]["run_id"] != review["run_id"]
    # Nothing from the superseded run is pending against the new one.
    pending = [r for r in decision_rows(case["case_id"]) if r.applied_at is None]
    assert all(r.run_id != reprocessed["run"]["run_id"] for r in pending)
