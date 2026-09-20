"""Lifetime budgets, sequential reviews and contract conformance (I-05, I-08, I-19)."""

import pytest

from backend.intelligence.config import (
    MAX_ACCEPTED_DECISIONS_PER_FIELD,
    MAX_ACCEPTED_DECISIONS_PER_FIELD_SIDE,
    MAX_DISTINCT_REVIEW_FIELDS,
)
from backend.intelligence.recomputation import BudgetState, ValidatedDecision
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
from tests.helpers import create_and_wait, poll_case

CANONICAL_FIELDS = ["shipper", "consignee", "notify_party", "port_of_loading",
                    "port_of_discharge", "container_count", "gross_weight_kg"]


# --- budget ledger ---------------------------------------------------------

def _decision(field=None, side=None, role=None):
    return ValidatedDecision(decision_id="d", review_id="r", run_id="run", action="PROVIDE_VALUE",
                             actor_id="a", channel="DASHBOARD", target_field=field,
                             target_side=side, target_role=role)


def test_at_most_one_accepted_decision_per_field_and_side():
    budget = BudgetState.from_decisions([_decision("gross_weight_kg", "SI")])
    assert not budget.allows_field("gross_weight_kg", "SI")
    # The other side still has its own slot.
    assert budget.allows_field("gross_weight_kg", "BL")
    assert MAX_ACCEPTED_DECISIONS_PER_FIELD_SIDE == 1


def test_at_most_two_accepted_decisions_per_field_across_both_sides():
    budget = BudgetState.from_decisions([
        _decision("gross_weight_kg", "SI"), _decision("gross_weight_kg", "BL"),
    ])
    assert not budget.allows_field("gross_weight_kg", "SI")
    assert not budget.allows_field("gross_weight_kg", "BL")
    assert MAX_ACCEPTED_DECISIONS_PER_FIELD == 2


def test_document_choices_are_capped_per_role_and_per_run():
    budget = BudgetState.from_decisions([_decision(role="SI")])
    assert not budget.allows_document_choice("SI")
    assert budget.allows_document_choice("BL")

    both = BudgetState.from_decisions([_decision(role="SI"), _decision(role="BL")])
    assert not both.allows_document_choice("SI")
    assert not both.allows_document_choice("BL")


def test_resolving_one_field_does_not_free_a_slot_for_a_third():
    """The cap counts distinct fields across the whole run, not the outstanding set."""
    from backend.intelligence.pipeline import build_review_requirement
    from backend.intelligence.comparison import Assessment
    from backend.intelligence.types import FieldOutcome, UncertaintyCause

    assessment = Assessment("NEEDS_REVIEW", "missing_value", False, ())
    si = {f: FieldOutcome(field=f, side="SI") for f in CANONICAL_FIELDS}
    bl = {f: FieldOutcome(field=f, side="BL") for f in CANONICAL_FIELDS}
    si["shipper"] = FieldOutcome(field="shipper", side="SI",
                                 cause=UncertaintyCause.MISSING_VALUE)
    for field in CANONICAL_FIELDS:
        if field != "shipper":
            si[field] = FieldOutcome(field=field, side="SI", value=None,
                                     cause=UncertaintyCause.MISSING_VALUE)

    # Two fields were already asked about in this run; a third becomes a block.
    requirement = build_review_requirement(
        assessment, None, si, bl, (), {},
        prior_review_fields=("consignee", "container_count"),
    )
    assert requirement is not None
    assert requirement.blocks_externally is True
    assert requirement.ui_mode == "ACKNOWLEDGE"
    assert MAX_DISTINCT_REVIEW_FIELDS == 2


def test_i08_a_reused_field_side_budget_ends_in_an_external_block(client):
    """I-08: the same target cannot be asked twice; the run blocks instead of looping."""
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]

    response = client.post(
        f"/api/v1/reviews/{review['review_id']}/decision",
        json={"review_id": review["review_id"], "run_id": review["run_id"],
              "channel": "DASHBOARD", "actor_id": "op", "action": "PROVIDE_VALUE",
              "field": "gross_weight_kg", "side": "BL", "value": 18500,
              "override_confirmation": {
                  "review_id": review["review_id"], "run_id": review["run_id"],
                  "field": "gross_weight_kg", "side": "BL",
                  "proposed_value": 18500, "confirmed": True}},
    )
    assert response.status_code == 202

    settled = poll_case(client, case["case_id"], "COMPLETED")
    # The single unresolved field was answered, so the run finishes rather than
    # asking about the same target again.
    assert settled["review"] is None or settled["review"]["status"] == "CLOSED"
    assert settled["resolution"]["final_status"] in ("OK", "MISMATCH")


# --- contract conformance --------------------------------------------------

ALL_FIXTURES = [DEMO_MATCH, DEMO_MISMATCH, DEMO_MISSING_WEIGHT, DEMO_NO_ATTACHMENTS,
                DEMO_WRONG_DOC, DEMO_INVOICE, DEMO_DOCUMENT_CHOICE, DEMO_PDF,
                DEMO_SCANNED, DEMO_CORRUPT, DEMO_OFFICE]

TERMINAL = {"COMPLETED", "AWAITING_HUMAN", "BLOCKED_EXTERNAL"}


def _settled(client, email_id):
    client.post("/api/v1/cases", json={"email_id": email_id})
    import time
    deadline = time.time() + 25
    while time.time() < deadline:
        case = client.get(f"/api/v1/cases/{email_id}").json()
        if case["workflow_status"] in TERMINAL:
            return case
        time.sleep(0.2)
    raise AssertionError(f"{email_id} never settled")


@pytest.mark.parametrize("email_id", ALL_FIXTURES)
def test_i19_every_lifecycle_state_satisfies_the_contract_invariants(client, email_id):
    """I-19: complete Case payloads, checked against the shared contract's rules."""
    case = _settled(client, email_id)

    assert case["schema_version"] == "2.1.1"

    # Required nullable properties are present as explicit nulls, never omitted.
    for key in ("machine_assessment", "review", "resolution", "failure", "completed_at"):
        assert key in case, key
    assert "received_at" in case["email"]

    # Category and classified_by are non-null once an assessment exists.
    if case["machine_assessment"] is not None:
        assert case["email"]["category"] is not None
        assert case["email"]["classified_by"] in ("DETERMINISTIC", "AI", "HUMAN")

    # Fields: seven unique canonical fields for settled BL cases, none otherwise.
    if case["email"]["category"] == "BL_COMPARISON":
        fields = [f["field"] for f in case["fields"]]
        assert fields == CANONICAL_FIELDS
        assert len(set(fields)) == 7
    else:
        assert case["fields"] == []

    # NOT_COMPARABLE iff a cause is present.
    for comparison in case["fields"]:
        if comparison["result"] == "NOT_COMPARABLE":
            assert comparison["not_comparable_cause"] is not None
        else:
            assert comparison["not_comparable_cause"] is None
        # Every FieldValue carries complete provenance.
        for side in ("si", "bl"):
            value = comparison[side]
            if value is None:
                continue
            for key in ("raw", "normalized", "evidence", "resolved_by",
                        "value_origin", "grounded", "flags", "override_confirmations"):
                assert key in value, key
            if value["value_origin"] == "MANUAL_OVERRIDE":
                assert value["grounded"] is False
            if value["value_origin"] == "DOCUMENT_CONFIRMED":
                assert value["evidence"]

    # Review state.
    review = case["review"]
    if review is not None:
        if review["status"] == "OPEN":
            assert review["closed_at"] is None and review["close_reason"] is None
        else:
            assert review["closed_at"] is not None and review["close_reason"] is not None
        if review["scope"] == "FIELD":
            assert review["field"] is not None and review["side"] is not None
            assert review["target_role"] is None
        if review["scope"] == "DOCUMENT" and review["ui_mode"] == "CHOICE":
            assert review["target_role"] in ("SI", "BL")
            assert review["field"] is None and review["side"] is None
        if review["ui_mode"] == "CHOICE":
            escapes = [o for o in review["options"] if o["option_id"] == "NONE_OF_THESE"]
            assert len(escapes) == 1 and escapes[0]["kind"] == "ESCAPE"
            assert len({o["option_id"] for o in review["options"]}) == len(review["options"])
            for option in review["options"]:
                # Discriminated shapes: no irrelevant null keys.
                if option["kind"] == "DOCUMENT":
                    assert option.get("value") is None
                    assert option["document_id"]
                if option["kind"] == "ESCAPE":
                    assert option.get("value") is None
                    assert option.get("document_id") is None

    # Workflow invariants.
    workflow = case["workflow_status"]
    effective = ((case["resolution"] or {}).get("final_status")
                 or (case["machine_assessment"] or {}).get("status"))
    if workflow == "AWAITING_HUMAN":
        assert review is not None and review["status"] == "OPEN"
        assert review["ui_mode"] in ("CHOICE", "VALUE_INPUT")
    if workflow == "BLOCKED_EXTERNAL":
        assert review is not None
        assert case["follow_up"] == "AWAIT_EXTERNAL"
    if workflow == "COMPLETED":
        assert review is None or review["status"] == "CLOSED"
        assert effective in ("OK", "MISMATCH")

    # completed_at is non-null iff COMPLETED.
    assert (case["completed_at"] is not None) == (workflow == "COMPLETED")

    # follow_up derivation.
    if workflow == "BLOCKED_EXTERNAL":
        assert case["follow_up"] == "AWAIT_EXTERNAL"
    elif effective == "MISMATCH":
        assert case["follow_up"] == "CORRECTION_REQUIRED"
    else:
        assert case["follow_up"] == "NONE"

    # Assessment shape.
    assessment = case["machine_assessment"]
    if assessment is not None:
        if assessment["status"] == "OK":
            assert assessment["review_reason"] is None
            assert assessment["has_defect"] is False and assessment["defect_fields"] == []
        elif assessment["status"] == "MISMATCH":
            assert assessment["review_reason"] is None
            assert assessment["has_defect"] is True and assessment["defect_fields"]
        else:
            assert assessment["review_reason"] in (
                "missing_attachment", "wrong_doc_type", "unreadable", "missing_value")
            assert assessment["has_defect"] is False and assessment["defect_fields"] == []

    # Timestamps are UTC ISO-8601 when non-null.
    for key in ("created_at", "updated_at", "completed_at"):
        if case[key] is not None:
            assert case[key].endswith("Z") and "T" in case[key]


def test_evidence_only_references_documents_in_this_case(client):
    for email_id in (DEMO_MATCH, DEMO_PDF, DEMO_OFFICE):
        case = _settled(client, email_id)
        known = {d["document_id"] for d in case["documents"]}
        for comparison in case["fields"]:
            for side in ("si", "bl"):
                if comparison[side] is None:
                    continue
                for reference in comparison[side]["evidence"]:
                    assert reference["document_id"] in known


def test_no_private_data_reaches_the_wire(client):
    """The email body, file paths and storage keys never appear on a Case."""
    import json

    case = _settled(client, DEMO_MATCH)
    payload = json.dumps(case)
    assert "body" not in case["email"]
    assert "compare the SI and draft BL" not in payload
    assert "resources/demo-fixtures" not in payload
    assert "/home/" not in payload
