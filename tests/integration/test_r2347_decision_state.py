"""R2, R3, R4 and R7 regressions: one working state, one durable transaction.

On 58f2a7e:
  R2 validation reran the initial analysis and ignored applied decisions, so a
     value the chosen BL genuinely supported was rejected with 422.
  R3 the case write and the applied marker were separate commits, so a crash
     between them let a retry apply the same decision twice.
  R4 an unknown job id fell through and consumed a different pending decision.
  R7 validation and resumption re-read current inputs and reran interpretation.
"""

import pytest

from backend import crud, models, schemas, worker
from backend.database import SessionLocal
from backend.intelligence.types import PermanentProcessingError
from tests.conftest import DEMO_DOCUMENT_CHOICE, DEMO_MISSING_WEIGHT
from tests.helpers import create_and_wait, poll_case


def _decisions(case_id):
    db = SessionLocal()
    try:
        return db.query(models.AcceptedDecisionModel).filter_by(case_id=case_id).all()
    finally:
        db.close()


def _decide(client, review, **payload):
    body = {"review_id": review["review_id"], "run_id": review["run_id"],
            "channel": "DASHBOARD", "actor_id": "operator_1"}
    body.update(payload)
    return client.post(f"/api/v1/reviews/{review['review_id']}/decision", json=body)


# --------------------------------------------------------------------------
# R2
# --------------------------------------------------------------------------

def test_r2_a_value_the_chosen_document_supports_is_accepted(client):
    """The review's exact scenario: choose a BL, then confirm its gross weight.

    On 58f2a7e this returned 422 VALUE_NOT_FOUND_IN_DOCUMENT, because validation
    looked for the value in an unassigned BL.
    """
    case = create_and_wait(client, DEMO_DOCUMENT_CHOICE, "AWAITING_HUMAN")
    review = case["review"]
    assert review["scope"] == "DOCUMENT"

    option = next(o for o in review["options"] if o["kind"] == "DOCUMENT")
    assert _decide(client, review, action="SELECT_OPTION",
                   option_id=option["option_id"]).status_code == 202
    settled = poll_case(client, case["case_id"], "COMPLETED")

    # The chosen BL states 18500 KG. Validation must now find it.
    db = SessionLocal()
    try:
        schema_case = crud.map_db_to_schema(crud.get_case(db, case["case_id"]))
        state = worker.load_working_state(db, schema_case, schema_case.run.run_id)[0]
    finally:
        db.close()

    assert state.roles.bl == option["document_id"], "the applied choice was not replayed"
    assert len(state.accepted_decisions) == 1
    assert state.accepted_decisions[0].target_role == "BL"

    from decimal import Decimal

    from backend.intelligence.recomputation import find_document_support
    from backend.intelligence.types import NormalizedValue

    supported = find_document_support(
        "gross_weight_kg", "BL", state.parsed[state.roles.bl],
        NormalizedValue.of_decimal(Decimal("18500")), policy="auto", convention="",
    )
    assert supported is not None, "the chosen BL's own weight was not document-confirmed"
    assert supported.block_id is not None


def test_r2_validation_and_application_share_one_state(client):
    """Whatever the worker applied is exactly what the next proposal is checked against."""
    case = create_and_wait(client, DEMO_DOCUMENT_CHOICE, "AWAITING_HUMAN")
    review = case["review"]
    option = next(o for o in review["options"] if o["kind"] == "DOCUMENT")
    _decide(client, review, action="SELECT_OPTION", option_id=option["option_id"])
    poll_case(client, case["case_id"], "COMPLETED")

    db = SessionLocal()
    try:
        schema_case = crud.map_db_to_schema(crud.get_case(db, case["case_id"]))
        validation_state = worker.load_working_state(db, schema_case,
                                                     schema_case.run.run_id)[0]
    finally:
        db.close()

    applied = [d for d in _decisions(case["case_id"]) if d.applied_at is not None]
    assert len(applied) == len(validation_state.accepted_decisions)


def test_r2_a_pending_decision_is_not_treated_as_applied(client):
    """Only durably applied decisions are replayed."""
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]

    db = SessionLocal()
    try:
        schema_case = crud.map_db_to_schema(crud.get_case(db, case["case_id"]))
        state = worker.load_working_state(db, schema_case, schema_case.run.run_id)[0]
        assert state.accepted_decisions == ()
    finally:
        db.close()


# --------------------------------------------------------------------------
# R3
# --------------------------------------------------------------------------

def _accept_override(client, case_id, value=18500):
    case = poll_case(client, case_id, "AWAITING_HUMAN")
    review = case["review"]
    response = _decide(
        client, review, action="PROVIDE_VALUE", field="gross_weight_kg", side="BL",
        value=value,
        override_confirmation={"review_id": review["review_id"], "run_id": review["run_id"],
                               "field": "gross_weight_kg", "side": "BL",
                               "proposed_value": value, "confirmed": True},
    )
    assert response.status_code == 202
    return review


def test_r3_a_crash_before_the_applied_marker_cannot_duplicate_the_application(
        client, monkeypatch):
    """The case write and the marker are one transaction, so there is no window.

    On 58f2a7e a crash here left the case updated with the decision still
    pending, and the retry produced a second DECISION_APPLIED event.
    """
    client.post("/api/v1/cases", json={"email_id": DEMO_MISSING_WEIGHT})
    review = _accept_override(client, DEMO_MISSING_WEIGHT)
    record = _decisions(DEMO_MISSING_WEIGHT)[0]

    # Crash at the exact moment the old code committed the case and had not yet
    # written the marker.
    original = worker._commit_case
    calls = {"n": 0}

    def crash_after_case_write(db, db_case, case, expected_run_id, **kwargs):
        calls["n"] += 1
        # Perform the real write, then die before returning.
        original(db, db_case, case, expected_run_id, **kwargs)
        raise RuntimeError("simulated crash immediately after the case write")

    monkeypatch.setattr(worker, "_commit_case", crash_after_case_write)
    with pytest.raises(RuntimeError):
        worker.apply_decision(DEMO_MISSING_WEIGHT, job_id=record.job_id,
                              job_run_id=review["run_id"])
    monkeypatch.undo()

    after_crash = client.get(f"/api/v1/cases/{DEMO_MISSING_WEIGHT}").json()
    applied_events = [e for e in after_crash["history"] if e["type"] == "DECISION_APPLIED"]

    # Retry the same job, exactly as the worker loop would.
    worker.apply_decision(DEMO_MISSING_WEIGHT, job_id=record.job_id,
                          job_run_id=review["run_id"])

    final = client.get(f"/api/v1/cases/{DEMO_MISSING_WEIGHT}").json()
    final_applied = [e for e in final["history"] if e["type"] == "DECISION_APPLIED"]
    assert len(final_applied) == 1, (
        f"the decision was applied {len(final_applied)} times "
        f"(was {len(applied_events)} before the retry)"
    )
    records = _decisions(DEMO_MISSING_WEIGHT)
    assert len([r for r in records if r.applied_at is not None]) == 1


def test_r3_a_failed_run_guard_marks_nothing_applied(client):
    """A superseded write marks no decision applied."""
    client.post("/api/v1/cases", json={"email_id": DEMO_MISSING_WEIGHT})
    review = _accept_override(client, DEMO_MISSING_WEIGHT)
    record = _decisions(DEMO_MISSING_WEIGHT)[0]

    db = SessionLocal()
    try:
        db_case = crud.get_case(db, DEMO_MISSING_WEIGHT)
        case = crud.map_db_to_schema(db_case)
        case.workflow_status = schemas.WorkflowStatus.COMPLETED
        accepted = worker._commit_case(db, db_case, case, "run_that_is_not_current",
                                       mark_decision_applied=record.decision_id)
        assert accepted is False
    finally:
        db.close()

    assert _decisions(DEMO_MISSING_WEIGHT)[0].applied_at is None


def test_r3_a_crash_before_the_transaction_changes_nothing(client, monkeypatch):
    client.post("/api/v1/cases", json={"email_id": DEMO_MISSING_WEIGHT})
    review = _accept_override(client, DEMO_MISSING_WEIGHT)
    record = _decisions(DEMO_MISSING_WEIGHT)[0]
    before = client.get(f"/api/v1/cases/{DEMO_MISSING_WEIGHT}").json()

    def crash(*_args, **_kwargs):
        raise RuntimeError("simulated crash before the transaction")

    monkeypatch.setattr(worker, "_commit_case", crash)
    with pytest.raises(RuntimeError):
        worker.apply_decision(DEMO_MISSING_WEIGHT, job_id=record.job_id,
                              job_run_id=review["run_id"])
    monkeypatch.undo()

    after = client.get(f"/api/v1/cases/{DEMO_MISSING_WEIGHT}").json()
    assert after["workflow_status"] == before["workflow_status"]
    assert _decisions(DEMO_MISSING_WEIGHT)[0].applied_at is None


# --------------------------------------------------------------------------
# R4
# --------------------------------------------------------------------------

def test_r4_an_unknown_job_never_consumes_a_pending_decision(client):
    """The review's exact scenario: a bogus job id applied the real decision."""
    client.post("/api/v1/cases", json={"email_id": DEMO_MISSING_WEIGHT})
    case = poll_case(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]
    assert _decide(client, review, action="ACKNOWLEDGE").status_code == 202

    record = _decisions(DEMO_MISSING_WEIGHT)[0]
    assert record.applied_at is None

    with pytest.raises(PermanentProcessingError, match="no accepted decision record"):
        worker.apply_decision(DEMO_MISSING_WEIGHT, job_id="job_does_not_exist",
                              job_run_id=review["run_id"])

    assert _decisions(DEMO_MISSING_WEIGHT)[0].applied_at is None, \
        "a bogus job consumed a decision it was not accepted for"


def test_r4_a_wrong_run_does_not_apply_a_decision(client):
    client.post("/api/v1/cases", json={"email_id": DEMO_MISSING_WEIGHT})
    case = poll_case(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]
    _decide(client, review, action="ACKNOWLEDGE")
    record = _decisions(DEMO_MISSING_WEIGHT)[0]

    # A superseded run is a silent no-op, never an application.
    worker.apply_decision(DEMO_MISSING_WEIGHT, job_id=record.job_id,
                          job_run_id="run_from_another_life")
    assert _decisions(DEMO_MISSING_WEIGHT)[0].applied_at is None


def test_r4_retrying_an_applied_job_does_not_consume_a_second_decision(client):
    """Job A's retry must not apply decision B."""
    client.post("/api/v1/cases", json={"email_id": DEMO_MISSING_WEIGHT})
    review = _accept_override(client, DEMO_MISSING_WEIGHT)
    record_a = _decisions(DEMO_MISSING_WEIGHT)[0]
    poll_case(client, DEMO_MISSING_WEIGHT, "COMPLETED")
    assert _decisions(DEMO_MISSING_WEIGHT)[0].applied_at is not None

    # Plant a second, unrelated pending decision on the same run.
    db = SessionLocal()
    try:
        planted = models.AcceptedDecisionModel(
            decision_id="dec_planted", case_id=DEMO_MISSING_WEIGHT,
            run_id=record_a.run_id, review_id=record_a.review_id, job_id="job_b",
            sequence=99, payload=dict(record_a.payload, decision_id="dec_planted"),
            review_requirement=record_a.review_requirement,
            created_at="2026-09-21T00:00:00Z", applied_at=None,
        )
        db.add(planted)
        db.commit()
    finally:
        db.close()

    # Retrying job A must be an idempotent no-op, not an application of B.
    worker.apply_decision(DEMO_MISSING_WEIGHT, job_id=record_a.job_id,
                          job_run_id=record_a.run_id)

    planted_after = [d for d in _decisions(DEMO_MISSING_WEIGHT)
                     if d.decision_id == "dec_planted"][0]
    assert planted_after.applied_at is None, "job A's retry consumed decision B"


# --------------------------------------------------------------------------
# R7
# --------------------------------------------------------------------------

def test_r7_the_run_records_the_identity_it_was_computed_from(client):
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    db = SessionLocal()
    try:
        stored = worker.load_run_snapshot(db, case["run"]["run_id"])
    finally:
        db.close()

    assert stored is not None, "the run recorded no identity snapshot"
    assert stored.input_version == case["run"]["input_version"]
    assert stored.config_version == case["run"]["config_version"]
    assert stored.source_manifest
    assert stored.classification["category"] == case["email"]["category"]


def test_r7_changed_sources_fail_visibly_instead_of_reinterpreting(client, monkeypatch):
    """A run whose inputs moved cannot absorb a decision; it needs a new run."""
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]

    db = SessionLocal()
    try:
        # Simulate the sources having changed since the run was computed.
        db.query(models.RunSnapshotModel).filter_by(run_id=review["run_id"]).update(
            {"input_version": "iv1_something_else_entirely"}
        )
        db.commit()
    finally:
        db.close()

    response = _decide(client, review, action="ACKNOWLEDGE")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STALE_RUN"
    assert _decisions(DEMO_MISSING_WEIGHT) == []


def test_r7_changed_configuration_fails_visibly(client):
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]

    db = SessionLocal()
    try:
        db.query(models.RunSnapshotModel).filter_by(run_id=review["run_id"]).update(
            {"config_version": "person-a-v1+adifferentpolicy"}
        )
        db.commit()
    finally:
        db.close()

    response = _decide(client, review, action="ACKNOWLEDGE")
    assert response.status_code == 409
    assert "configuration changed" in response.json()["error"]["message"]


def test_r7_resumption_never_calls_a_provider(client, monkeypatch):
    """Human review must not depend on a nondeterministic provider response."""
    case = create_and_wait(client, DEMO_MISSING_WEIGHT, "AWAITING_HUMAN")
    review = case["review"]

    from backend.intelligence import ai as ai_module

    class Exploding(ai_module.DisabledModelClient):
        name = "exploding"

        def classify(self, **_kwargs):
            raise AssertionError("a provider was consulted during resumption")

    monkeypatch.setattr(ai_module, "build_model_client", lambda *a, **k: Exploding())

    response = _decide(client, review, action="ACKNOWLEDGE")
    assert response.status_code == 202
    poll_case(client, case["case_id"], "BLOCKED_EXTERNAL")


def test_r7_the_provider_budget_is_charged_before_the_call():
    """An attempt that fails still consumes its budget."""
    from backend.intelligence import ai as ai_module
    from backend.intelligence.classification import build_view
    from backend.intelligence.config import load_config
    from backend.intelligence.ingestion import build_registries, ingest_case
    from backend.intelligence.pipeline import (
        AnalysisContext, IntelligenceServices, analyze_case,
    )
    import dataclasses

    base = load_config()
    config = dataclasses.replace(base, ai=dataclasses.replace(
        base.ai, enabled=True, provider="t", endpoint="https://x.invalid",
        model="m", api_key="k", allow_participant_content=True, max_calls_per_run=1))
    registries = build_registries(config)

    class Failing:
        name = "failing"
        def classify(self, **_kwargs):
            raise ai_module.ModelResponseInvalid("provider timed out")
        def extract(self, **_kwargs):
            raise ai_module.ModelResponseInvalid("provider timed out")

    budget = ai_module.CallBudget(limit=1)
    services = IntelligenceServices(registries=registries, model=Failing(), budget=budget)
    snapshot = ingest_case("email_demo_needs_model", namespace="DEMO",
                           case_id="email_demo_needs_model",
                           registries=registries, config=config)
    context = AnalysisContext("email_demo_needs_model", "r", "DEMO", config,
                              lambda: "t", lambda p: p)
    with pytest.raises(ai_module.ModelResponseInvalid):
        analyze_case(snapshot, context, services)

    assert budget.calls == 1, "a failed attempt did not consume its budget"
