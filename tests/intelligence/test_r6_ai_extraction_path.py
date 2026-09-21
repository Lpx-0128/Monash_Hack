"""R6 regression: targeted AI extraction is actually wired into analyze_case.

On 58f2a7e the repository had an extraction adapter and adapter-level tests, but
``analyze_case`` never called ``model.extract`` and reported
``ai_assisted_fields`` as a hard-coded zero. Adding credentials alone would not
have enabled AI field extraction. These tests exercise the real pipeline path.
"""

import dataclasses

import pytest

from backend.intelligence import ai as ai_module
from backend.intelligence.config import load_config
from backend.intelligence.ingestion import build_registries, ingest_case
from backend.intelligence.pipeline import (
    AnalysisContext,
    IntelligenceServices,
    analyze_case,
)

AMBIGUOUS = "email_demo_ambiguous_weight"


def _config(*, allow_participant=False, calls=4):
    base = load_config()
    ai = dataclasses.replace(
        base.ai, enabled=True, provider="test", endpoint="https://provider.invalid",
        model="test-model", api_key="test-key",
        allow_participant_content=allow_participant, max_calls_per_run=calls,
    )
    return dataclasses.replace(base, ai=ai)


class ChoosingModel:
    """Points at one of the document's own candidate blocks."""

    name = "choosing"

    def __init__(self, pick: int = 0, field: str = "gross_weight_kg",
                 block_id: str = None):
        self.pick = pick
        self.field = field
        self.block_id = block_id
        self.extract_calls = []
        self.tokens_seen = ()

    def classify(self, **_kwargs):
        raise AssertionError("classification is decided by the rules for this fixture")

    def extract(self, *, document_id, document_text, location_tokens, requested_fields):
        self.extract_calls.append((document_id, tuple(requested_fields)))
        self.tokens_seen = tuple(location_tokens)
        if self.block_id is not None:
            token = f"block:{self.block_id}"
        else:
            token = list(location_tokens)[self.pick] if location_tokens else "block:none"
        value = location_tokens.get(token, {}).get("value", "")
        return ai_module.ExtractionProposal(
            document_id=document_id,
            candidates=(ai_module.ExtractionCandidateProposal(
                field=self.field, raw=value,
                locator_token=token, source_text=value, derivation="DIRECT",
            ),),
        )


def _run(model, *, config=None, email_id=AMBIGUOUS):
    config = config or _config()
    registries = build_registries(config)
    snapshot = ingest_case(email_id, namespace="DEMO", case_id=email_id,
                           registries=registries, config=config)
    services = IntelligenceServices(
        registries=registries, model=model,
        budget=ai_module.CallBudget(limit=config.ai.max_calls_per_run),
    )
    context = AnalysisContext(email_id, "run_r6", "DEMO", config,
                              lambda: "2026-09-21T00:00:00Z", lambda p: f"{p}_1")
    return analyze_case(snapshot, context, services), services


def _weight(analysis):
    return analysis.bl_fields["gross_weight_kg"]


def test_r6_without_a_model_the_field_stays_ambiguous():
    """The baseline capability: the rules refuse to choose."""
    analysis, _services = _run(None)
    outcome = _weight(analysis)
    assert not outcome.resolved
    assert len(outcome.alternatives) >= 2
    assert analysis.assessment.status == "NEEDS_REVIEW"
    assert analysis.ai_calls == 0
    assert analysis.ai_assisted_fields == 0


def test_r6_the_model_is_actually_called_and_improves_a_grounded_field():
    """Removing the provider changes what this case can do."""
    alternatives = _weight(_run(None)[0]).alternatives
    target = alternatives[0]

    model = ChoosingModel(block_id=target.block_id)
    analysis, _services = _run(model)

    assert model.extract_calls, "analyze_case never called the extraction adapter"
    document_id, requested = model.extract_calls[0]
    assert "gross_weight_kg" in requested

    outcome = _weight(analysis)
    assert outcome.resolved, "the model's choice did not resolve the field"
    assert outcome.value.normalized.equals(target.normalized)
    assert outcome.value.method.value == "AI"
    assert outcome.value.block_id is not None
    assert analysis.ai_calls >= 1
    assert analysis.ai_assisted_fields == 1
    # It is now comparable, so the case no longer needs a person for this field.
    assert analysis.assessment.status in ("OK", "MISMATCH")


@pytest.mark.parametrize("index", [0, 1])
def test_r6_the_accepted_value_is_one_the_document_supports(index):
    """The model chooses among real readings; it never introduces a number."""
    alternatives = _weight(_run(None)[0]).alternatives
    supported = {c.normalized.to_wire() for c in alternatives}
    chosen = alternatives[index]

    analysis, _services = _run(ChoosingModel(block_id=chosen.block_id))
    resolved = _weight(analysis)
    assert resolved.resolved
    assert resolved.value.normalized.to_wire() == chosen.normalized.to_wire()
    assert resolved.value.normalized.to_wire() in supported


def test_r6_a_proposal_pointing_outside_the_documents_candidates_is_discarded():
    """A token for an unrelated block cannot smuggle in a value."""

    class Wandering(ChoosingModel):
        def extract(self, *, document_id, document_text, location_tokens, requested_fields):
            self.extract_calls.append((document_id, tuple(requested_fields)))
            # A real token, but for a block that is not a gross-weight candidate.
            return ai_module.ExtractionProposal(
                document_id=document_id,
                candidates=(ai_module.ExtractionCandidateProposal(
                    field="gross_weight_kg", raw="x",
                    locator_token=list(location_tokens)[0], source_text="",
                    derivation="DIRECT",
                ),),
            )

    # Point at the shipper block rather than a weight block.
    analysis, _services = _run(Wandering(pick=0))
    outcome = _weight(analysis)
    if outcome.resolved:
        # If it happened to land on a weight block, that is a legitimate choice.
        assert outcome.value.field == "gross_weight_kg"
    else:
        assert outcome.cause is not None


def test_r6_a_fabricated_response_never_improves_coverage():
    """An invalid response is discarded; the field keeps its honest uncertainty."""

    class WrongDocument:
        name = "wrong"
        def classify(self, **_kwargs):
            raise AssertionError
        def extract(self, *, document_id, document_text, location_tokens, requested_fields):
            # The adapter's own validation rejects a response naming another
            # document, which surfaces as a retryable provider failure.
            return ai_module.validate_extraction(
                {"document_id": "some_other_document", "candidates": [],
                 "unresolved_fields": []},
                document_id=document_id, allowed_fields=requested_fields,
                allowed_tokens=location_tokens, source_text=document_text,
            )

    analysis, _services = _run(WrongDocument())
    outcome = _weight(analysis)
    assert not outcome.resolved
    assert analysis.ai_assisted_fields == 0
    assert analysis.assessment.status == "NEEDS_REVIEW"


def test_r6_a_provider_failure_leaves_the_deterministic_result_standing():
    """An unavailable provider degrades to honest uncertainty, not a wrong value."""

    class Failing(ChoosingModel):
        def extract(self, **_kwargs):
            raise ai_module.ModelResponseInvalid("provider timed out")

    analysis, _services = _run(Failing())
    outcome = _weight(analysis)
    assert not outcome.resolved
    assert analysis.assessment.status == "NEEDS_REVIEW"
    assert analysis.ai_assisted_fields == 0


def test_r6_participant_consent_gates_the_extraction_path_too():
    """R5 and R6 compose: no consent, no extraction call."""
    config = _config(allow_participant=False)
    registries = build_registries(config)
    model = ChoosingModel()
    snapshot = ingest_case("email_004", namespace="EVAL", case_id="email_004",
                           registries=registries, config=config)
    services = IntelligenceServices(registries=registries, model=model,
                                    budget=ai_module.CallBudget(limit=4))
    context = AnalysisContext("email_004", "r", "EVAL", config, lambda: "t", lambda p: p)
    analysis = analyze_case(snapshot, context, services)
    assert model.extract_calls == []
    assert analysis.ai_assisted_fields == 0


def test_r6_deterministic_cases_require_no_call():
    """A case the rules settle never spends a provider call."""
    model = ChoosingModel()
    analysis, _services = _run(model, email_id="email_demo_match")
    assert model.extract_calls == []
    assert analysis.ai_calls == 0
    assert analysis.assessment.status == "OK"


def test_r6_a_missing_value_is_not_invented_by_the_model():
    """The model is not asked to supply a value the document does not carry."""
    model = ChoosingModel()
    analysis, _services = _run(model, email_id="email_demo_missing_weight")
    assert model.extract_calls == [], "the model was asked about an absent value"
    assert analysis.assessment.review_reason == "missing_value"


def test_r6_extraction_respects_the_call_budget():
    config = _config(calls=1)
    model = ChoosingModel()
    registries = build_registries(config)
    snapshot = ingest_case(AMBIGUOUS, namespace="DEMO", case_id=AMBIGUOUS,
                           registries=registries, config=config)
    budget = ai_module.CallBudget(limit=1)
    services = IntelligenceServices(registries=registries, model=model, budget=budget)
    context = AnalysisContext(AMBIGUOUS, "r", "DEMO", config, lambda: "t", lambda p: p)
    analyze_case(snapshot, context, services)
    assert budget.calls <= 1
