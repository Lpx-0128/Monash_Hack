"""C1 regression: accepted AI interpretations must survive resumption.

On 675f0d3 ``load_working_state`` disabled the model and reran ``analyze_case``,
so the run's AI classification and any AI-resolved field were silently replaced
by a rules-only result. Acknowledging an AI-classified comparison then crashed
with ``KeyError: 'shipper'``. These tests fail on that commit.
"""

import pytest

from backend import crud, models, schemas, worker
from backend.database import SessionLocal
from backend.intelligence import ai as ai_module
from backend.intelligence.ingestion import ingest_case
from backend.intelligence.pipeline import (
    AnalysisContext,
    IntelligenceServices,
    analyze_case,
)

NEEDS_MODEL = "email_demo_needs_model"
AMBIGUOUS = "email_demo_ambiguous_weight"


class NoProvider(ai_module.DisabledModelClient):
    """Any provider call during resumption is a test failure."""

    name = "forbidden"

    def classify(self, **_kwargs):
        raise AssertionError("a provider was consulted during resumption")

    def extract(self, **_kwargs):
        raise AssertionError("a provider was consulted during resumption")


@pytest.fixture
def ai_enabled(monkeypatch):
    monkeypatch.setenv("INTELLIGENCE_AI_ENABLED", "true")
    monkeypatch.setenv("INTELLIGENCE_AI_PROVIDER", "test")
    monkeypatch.setenv("INTELLIGENCE_AI_ENDPOINT", "https://provider.invalid")
    monkeypatch.setenv("INTELLIGENCE_AI_MODEL", "test-model")
    monkeypatch.setenv("INTELLIGENCE_AI_API_KEY", "test-key")
    crud.reset_intelligence_cache()
    yield
    crud.reset_intelligence_cache()


def _with_model(monkeypatch, model):
    """Install a model for the automated pass only."""
    original = worker._build_services

    def build(snapshot=None):
        services = original(snapshot)
        services.model = model
        return services

    monkeypatch.setattr(worker, "_build_services", build)
    return original


def _forbid_provider(monkeypatch, original):
    def build(snapshot=None):
        services = original(snapshot)
        services.model = NoProvider()
        return services

    monkeypatch.setattr(worker, "_build_services", build)


def _process(email_id):
    db = SessionLocal()
    try:
        case = crud.create_case_with_job(db, email_id)
    finally:
        db.close()
    worker.process_case(email_id, job_id="job_initial", job_run_id=case.run.run_id)
    return case.run.run_id


def _case(email_id):
    db = SessionLocal()
    try:
        return crud.map_db_to_schema(crud.get_case(db, email_id))
    finally:
        db.close()


class Classifier:
    """Classifies the fixture the rules cannot decide."""

    name = "classifier"

    def classify(self, **_kwargs):
        return ai_module.ClassificationProposal(
            category="BL_COMPARISON",
            reason="the sender asks for a read on two documents that disagree",
            evidence_quotes=(),
        )

    def extract(self, *, document_id, **_kwargs):
        return ai_module.ExtractionProposal(document_id=document_id)


# --------------------------------------------------------------------------
# C1-A: AI classification survives, and acknowledgment does not crash
# --------------------------------------------------------------------------

def test_c1a_ai_classification_survives_resumption(ai_enabled, monkeypatch):
    original = _with_model(monkeypatch, Classifier())
    run_id = _process(NEEDS_MODEL)

    persisted = _case(NEEDS_MODEL)
    assert persisted.email.category is schemas.EmailCategory.BL_COMPARISON
    assert persisted.email.classified_by is schemas.ResolvedBy.AI

    _forbid_provider(monkeypatch, original)
    db = SessionLocal()
    try:
        state, _ctx, _snap, restored, _applied = worker.load_working_state(
            db, persisted, run_id
        )
    finally:
        db.close()

    assert restored["category"] == "BL_COMPARISON", "the AI classification was lost"
    assert restored["classified_by"] == "AI"
    assert state.category == "BL_COMPARISON"


def test_c1a_acknowledging_an_ai_classified_case_reaches_blocked_external(
        client, ai_enabled, monkeypatch):
    """The reviewer's crash: KeyError 'shipper' on apply_decision."""
    original = _with_model(monkeypatch, Classifier())
    run_id = _process(NEEDS_MODEL)

    case = _case(NEEDS_MODEL)
    assert case.review is not None
    review = case.review

    _forbid_provider(monkeypatch, original)
    response = client.post(
        f"/api/v1/reviews/{review.review_id}/decision",
        json={"review_id": review.review_id, "run_id": run_id, "channel": "DASHBOARD",
              "actor_id": "operator", "action": "ACKNOWLEDGE"},
    )
    assert response.status_code == 202

    db = SessionLocal()
    try:
        record = db.query(models.AcceptedDecisionModel).filter_by(
            case_id=NEEDS_MODEL).first()
        job_id = record.job_id
    finally:
        db.close()

    # This raised KeyError: 'shipper' on 675f0d3.
    worker.apply_decision(NEEDS_MODEL, job_id=job_id, job_run_id=run_id)

    settled = _case(NEEDS_MODEL)
    assert settled.workflow_status is schemas.WorkflowStatus.BLOCKED_EXTERNAL
    assert settled.email.category is schemas.EmailCategory.BL_COMPARISON
    assert settled.follow_up is schemas.FollowUp.AWAIT_EXTERNAL


# --------------------------------------------------------------------------
# C1-B: an AI-resolved field stays resolved
# --------------------------------------------------------------------------

def _ambiguous_alternatives():
    config = crud.intelligence_config()
    registries = crud.intelligence_registries()
    snapshot = ingest_case(AMBIGUOUS, namespace="DEMO", case_id=AMBIGUOUS,
                           registries=registries, config=config)
    analysis = analyze_case(
        snapshot,
        AnalysisContext(AMBIGUOUS, "probe", "DEMO", config, lambda: "t", lambda p: p),
        IntelligenceServices(registries=registries),
    )
    return analysis.bl_fields["gross_weight_kg"].alternatives


class ChoosesBlock:
    name = "chooser"

    def __init__(self, candidate):
        self.candidate = candidate

    def classify(self, **_kwargs):
        raise AssertionError("classification is decided by the rules here")

    def extract(self, *, document_id, **_kwargs):
        return ai_module.ExtractionProposal(
            document_id=document_id,
            candidates=(ai_module.ExtractionCandidateProposal(
                field="gross_weight_kg", raw=self.candidate.raw,
                locator_token=f"block:{self.candidate.block_id}",
                source_text=self.candidate.raw, derivation="DIRECT",
            ),),
        )


def test_c1b_an_ai_resolved_field_survives_resumption(ai_enabled, monkeypatch):
    target = _ambiguous_alternatives()[0]
    original = _with_model(monkeypatch, ChoosesBlock(target))
    run_id = _process(AMBIGUOUS)

    persisted = _case(AMBIGUOUS)
    weight = next(f for f in persisted.fields if f.field.value == "gross_weight_kg")
    assert weight.bl is not None
    assert weight.bl.normalized == target.normalized.to_wire()
    assert weight.bl.resolved_by is schemas.ResolvedBy.AI

    _forbid_provider(monkeypatch, original)
    db = SessionLocal()
    try:
        state, _ctx, _snap, _restored, _applied = worker.load_working_state(
            db, persisted, run_id
        )
    finally:
        db.close()

    outcome = state.bl_fields["gross_weight_kg"]
    assert outcome.resolved, "the AI-resolved field became unresolved again"
    assert outcome.value.normalized.to_wire() == target.normalized.to_wire()
    assert outcome.value.method.value == "AI"
    # Provenance and the block binding survive, so it can still be re-grounded.
    assert "AI_PROPOSED" in outcome.value.flags
    assert outcome.value.block_id == target.block_id
    assert outcome.value.evidence


def test_c1b_a_human_correction_elsewhere_preserves_the_ai_weight(
        client, ai_enabled, monkeypatch):
    """Resolving another field must not reopen one the model already settled."""
    target = _ambiguous_alternatives()[0]
    original = _with_model(monkeypatch, ChoosesBlock(target))
    run_id = _process(AMBIGUOUS)
    _forbid_provider(monkeypatch, original)

    persisted = _case(AMBIGUOUS)
    before = next(f for f in persisted.fields if f.field.value == "gross_weight_kg")
    assert before.bl.normalized == target.normalized.to_wire()

    db = SessionLocal()
    try:
        state, _ctx, _snap, _restored, _applied = worker.load_working_state(
            db, persisted, run_id
        )
    finally:
        db.close()
    assert state.bl_fields["gross_weight_kg"].resolved


def test_c1_state_is_equal_before_and_after_resumption(ai_enabled, monkeypatch):
    """Assert the machine state itself matches, not merely that nothing crashed."""
    target = _ambiguous_alternatives()[0]
    original = _with_model(monkeypatch, ChoosesBlock(target))
    run_id = _process(AMBIGUOUS)
    persisted = _case(AMBIGUOUS)

    db = SessionLocal()
    try:
        stored = worker.load_run_snapshot(db, run_id)
        recorded = dict(stored.machine_state)
        _forbid_provider(monkeypatch, original)
        state, _ctx, _snap, restored, _applied = worker.load_working_state(
            db, persisted, run_id
        )
    finally:
        db.close()

    from backend.intelligence import wire

    for side in ("si_fields", "bl_fields"):
        for name, payload in recorded[side].items():
            rehydrated = wire.field_outcome_to_json(restored[side][name])
            assert rehydrated == payload, f"{side}.{name} changed across resumption"
    assert restored["category"] == recorded["category"]
    assert restored["roles"].si == recorded["roles"]["si"]
    assert restored["roles"].bl == recorded["roles"]["bl"]


def test_c1_survives_a_process_restart(ai_enabled, monkeypatch):
    """A fresh session with no in-memory state restores the same interpretation."""
    target = _ambiguous_alternatives()[0]
    original = _with_model(monkeypatch, ChoosesBlock(target))
    run_id = _process(AMBIGUOUS)
    _forbid_provider(monkeypatch, original)

    # Drop every cache the process holds, as a restart would.
    crud.reset_intelligence_cache()

    db = SessionLocal()
    try:
        case = crud.map_db_to_schema(crud.get_case(db, AMBIGUOUS))
        state, _ctx, _snap, restored, _applied = worker.load_working_state(
            db, case, run_id
        )
    finally:
        db.close()

    assert restored["category"] == "BL_COMPARISON"
    assert state.bl_fields["gross_weight_kg"].resolved


# --------------------------------------------------------------------------
# C1: a missing snapshot must not silently rebuild an unverified state
# --------------------------------------------------------------------------

def test_c1_a_missing_machine_state_fails_visibly(client):
    from tests.helpers import create_and_wait

    case = create_and_wait(client, "email_demo_missing_weight", "AWAITING_HUMAN")
    run_id = case["run"]["run_id"]

    db = SessionLocal()
    try:
        db.query(models.RunSnapshotModel).filter_by(run_id=run_id).delete()
        db.commit()
        schema_case = crud.map_db_to_schema(crud.get_case(db, case["case_id"]))
        with pytest.raises(worker.RunStateUnavailable, match="no recorded machine state"):
            worker.load_working_state(db, schema_case, run_id)
    finally:
        db.close()


def test_c1_a_missing_machine_state_refuses_the_decision(client):
    from tests.helpers import create_and_wait

    case = create_and_wait(client, "email_demo_missing_weight", "AWAITING_HUMAN")
    review = case["review"]

    db = SessionLocal()
    try:
        db.query(models.RunSnapshotModel).filter_by(run_id=review["run_id"]).update(
            {"machine_state": None}
        )
        db.commit()
    finally:
        db.close()

    response = client.post(
        f"/api/v1/reviews/{review['review_id']}/decision",
        json={"review_id": review["review_id"], "run_id": review["run_id"],
              "channel": "DASHBOARD", "actor_id": "op", "action": "ACKNOWLEDGE"},
    )
    assert response.status_code == 409
    assert "cannot be resumed" in response.json()["error"]["message"]
    # Nothing was accepted.
    db = SessionLocal()
    try:
        assert db.query(models.AcceptedDecisionModel).filter_by(
            case_id=case["case_id"]).count() == 0
    finally:
        db.close()


def test_c1_the_run_manifest_is_preserved_verbatim(client):
    """An old run keeps the manifest it was computed under."""
    from tests.helpers import create_and_wait

    case = create_and_wait(client, "email_demo_match", "COMPLETED")
    db = SessionLocal()
    try:
        stored = worker.load_run_snapshot(db, case["run"]["run_id"])
    finally:
        db.close()

    assert stored.config_manifest is not None
    assert stored.config_manifest["code_release"]
    assert stored.config_manifest["policy_versions"]["ports"]
    assert stored.machine_state is not None
