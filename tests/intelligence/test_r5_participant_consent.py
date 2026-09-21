"""R5 regression: participant content must not reach a provider without consent.

On 58f2a7e ``allow_participant_content`` was loaded from configuration but never
consulted. With AI enabled, the classification fallback passed participant email
subjects and bodies to the model regardless. These tests fail on that commit.
"""

import dataclasses

import pytest

from backend.intelligence import ai as ai_module
from backend.intelligence.classification import build_view, classify_rules
from backend.intelligence.config import load_config
from backend.intelligence.ingestion import build_registries, ingest_case
from backend.intelligence.pipeline import (
    AnalysisContext,
    IntelligenceServices,
    analyze_case,
    model_permitted_for,
)


class RecordingModel:
    """Records every provider payload it is handed. It contacts nothing."""

    name = "recording"

    def __init__(self):
        self.calls = []

    def classify(self, *, subject, current_message, quoted_history, attachment_names):
        self.calls.append({"kind": "classify", "subject": subject,
                           "body": current_message, "quoted": quoted_history,
                           "attachments": tuple(attachment_names)})
        return ai_module.ClassificationProposal(
            category="GENERAL", reason="scripted", evidence_quotes=()
        )

    def extract(self, *, document_id, document_text, location_tokens, requested_fields):
        self.calls.append({"kind": "extract", "document_id": document_id,
                           "text": document_text})
        return ai_module.ExtractionProposal(document_id=document_id)


def _config(*, enabled: bool, allow_participant: bool):
    base = load_config()
    ai = dataclasses.replace(
        base.ai, enabled=enabled, provider="test", endpoint="https://provider.invalid",
        model="test-model", api_key="test-key", allow_participant_content=allow_participant,
    )
    return dataclasses.replace(base, ai=ai)


def _rules_fall_through_email(registries, config):
    """A participant email whose intent no deterministic rule can decide."""
    import json

    registry = registries["participant"]
    for email_id in registry.email_ids():
        record = json.loads((registry.inbox_dir / f"{email_id}.json").read_text())
        view = build_view(record["subject"], record["body"])
        if classify_rules(view).category is None:
            return email_id
    pytest.skip("no participant email falls through the rules in this corpus")


def _run(config, model, email_id):
    registries = build_registries(config)
    snapshot = ingest_case(email_id, namespace="EVAL", case_id=email_id,
                           registries=registries, config=config)
    services = IntelligenceServices(
        registries=registries, model=model,
        budget=ai_module.CallBudget(limit=config.ai.max_calls_per_run),
    )
    context = AnalysisContext(email_id, "run_r5", "EVAL", config,
                              lambda: "2026-09-21T00:00:00Z", lambda p: f"{p}_1")
    return snapshot, analyze_case(snapshot, context, services)


def test_r5_participant_content_never_reaches_the_model_without_consent():
    """AI enabled, consent withheld: zero provider calls, and no content sent."""
    config = _config(enabled=True, allow_participant=False)
    registries = build_registries(config)
    email_id = _rules_fall_through_email(registries, config)

    model = RecordingModel()
    snapshot, analysis = _run(config, model, email_id)

    assert snapshot.registry_kind == "participant"
    assert model.calls == [], "participant content was sent to the provider"
    assert analysis.ai_calls == 0
    # The case still settles, using the documented local fallback.
    assert analysis.category is not None
    # And the refusal is recorded rather than silent.
    assert any(d.code == "MODEL_NOT_USED" for d in analysis.diagnostics)


def test_r5_consent_is_independent_of_whether_ai_is_enabled():
    """Turning AI on does not imply permission to send this source's content."""
    config = _config(enabled=True, allow_participant=False)
    registries = build_registries(config)
    snapshot = ingest_case("email_004", namespace="EVAL", case_id="email_004",
                           registries=registries, config=config)
    services = IntelligenceServices(registries=registries, model=RecordingModel())

    permitted, reason = model_permitted_for(snapshot, config, services)
    assert permitted is False
    assert "not authorized" in reason


def test_r5_consent_allows_the_call():
    """With permission granted, the configured path is used normally."""
    config = _config(enabled=True, allow_participant=True)
    registries = build_registries(config)
    email_id = _rules_fall_through_email(registries, config)

    model = RecordingModel()
    snapshot, analysis = _run(config, model, email_id)

    assert [c["kind"] for c in model.calls] == ["classify"]
    assert analysis.ai_calls == 1
    assert analysis.classified_by == "AI"


def test_r5_synthetic_demo_sources_are_not_consent_gated():
    """Fixtures we authored carry no participant data, so they are unaffected."""
    config = _config(enabled=True, allow_participant=False)
    registries = build_registries(config)
    snapshot = ingest_case("email_demo_needs_model", namespace="DEMO",
                           case_id="email_demo_needs_model",
                           registries=registries, config=config)
    services = IntelligenceServices(registries=registries, model=RecordingModel())

    permitted, _reason = model_permitted_for(snapshot, config, services)
    assert snapshot.registry_kind == "synthetic_demo"
    assert permitted is True


def test_r5_the_worker_does_not_even_construct_a_client_without_consent(monkeypatch):
    """Defence in depth: no provider client exists for a non-consented source."""
    from backend import crud, worker

    monkeypatch.setenv("INTELLIGENCE_AI_ENABLED", "true")
    monkeypatch.setenv("INTELLIGENCE_AI_PROVIDER", "test")
    monkeypatch.setenv("INTELLIGENCE_AI_ENDPOINT", "https://provider.invalid")
    monkeypatch.setenv("INTELLIGENCE_AI_MODEL", "test-model")
    monkeypatch.setenv("INTELLIGENCE_AI_API_KEY", "test-key")
    monkeypatch.setenv("INTELLIGENCE_AI_ALLOW_PARTICIPANT_CONTENT", "false")
    crud.reset_intelligence_cache()
    try:
        registries = crud.intelligence_registries()
        config = crud.intelligence_config()
        participant = ingest_case("email_004", namespace="EVAL", case_id="email_004",
                                  registries=registries, config=config)
        demo = ingest_case("email_demo_match", namespace="DEMO",
                           case_id="email_demo_match",
                           registries=registries, config=config)

        assert isinstance(worker._build_services(participant).model,
                          ai_module.DisabledModelClient)
        # The authorised synthetic registry still gets the real client.
        assert isinstance(worker._build_services(demo).model, ai_module.HttpModelClient)
    finally:
        crud.reset_intelligence_cache()


def test_r5_no_credential_appears_in_a_refusal():
    """A refusal explains itself without leaking the key or the content."""
    config = _config(enabled=True, allow_participant=False)
    registries = build_registries(config)
    snapshot = ingest_case("email_004", namespace="EVAL", case_id="email_004",
                           registries=registries, config=config)
    services = IntelligenceServices(registries=registries, model=RecordingModel())
    _permitted, reason = model_permitted_for(snapshot, config, services)
    assert "test-key" not in reason
    assert snapshot.body[:40] not in reason
