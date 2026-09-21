"""C2 regression: conflicting model candidates must remain uncertain.

On 675f0d3 the per-field loop in ``ai_extract_side`` overwrote outcomes as
proposals arrived, so two genuinely different grounded readings became
"whichever came last", were counted as two assisted fields, and the case was
declared MISMATCH. These tests exercise the real pipeline and fail there.
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

def _ai_config():
    base = load_config()
    return dataclasses.replace(base, ai=dataclasses.replace(
        base.ai, enabled=True, provider="test", endpoint="https://provider.invalid",
        model="test-model", api_key="test-key", allow_participant_content=True))


def _alternatives(config):
    registries = build_registries(config)
    snapshot = ingest_case(AMBIGUOUS, namespace="DEMO", case_id=AMBIGUOUS,
                           registries=registries, config=config)
    analysis = analyze_case(
        snapshot,
        AnalysisContext(AMBIGUOUS, "probe", "DEMO", config, lambda: "t", lambda p: p),
        IntelligenceServices(registries=registries),
    )
    return snapshot, registries, analysis.bl_fields["gross_weight_kg"].alternatives


def _model_returning(candidates, unresolved=()):
    class Listing:
        name = "listing"

        def classify(self, **_kwargs):
            raise AssertionError("classification is decided by the rules here")

        def extract(self, *, document_id, **_kwargs):
            return ai_module.ExtractionProposal(
                document_id=document_id,
                candidates=tuple(
                    ai_module.ExtractionCandidateProposal(
                        field="gross_weight_kg", raw=c.raw,
                        locator_token=f"block:{c.block_id}", source_text=c.raw,
                        derivation="DIRECT")
                    for c in candidates
                ),
                unresolved_fields=tuple(unresolved),
            )

    return Listing()


def _run(config, registries, snapshot, model):
    return analyze_case(
        snapshot,
        AnalysisContext(AMBIGUOUS, "run", "DEMO", config, lambda: "t", lambda p: p),
        IntelligenceServices(registries=registries, model=model,
                             budget=ai_module.CallBudget(limit=4)),
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_c2_two_different_grounded_readings_stay_uncertain(reverse):
    """Whichever order they arrive in, the conflict is not resolved by the model."""
    config = _ai_config()
    snapshot, registries, alternatives = _alternatives(config)
    assert len(alternatives) >= 2
    listed = list(reversed(alternatives)) if reverse else list(alternatives)

    analysis = _run(config, registries, snapshot, _model_returning(listed))
    outcome = analysis.bl_fields["gross_weight_kg"]

    assert not outcome.resolved, "a conflict was silently resolved by ordering"
    assert analysis.assessment.status == "NEEDS_REVIEW"
    assert analysis.ai_assisted_fields == 0


def test_c2_an_identical_reading_listed_twice_counts_once():
    config = _ai_config()
    snapshot, registries, alternatives = _alternatives(config)
    chosen = alternatives[0]

    analysis = _run(config, registries, snapshot, _model_returning([chosen, chosen]))
    outcome = analysis.bl_fields["gross_weight_kg"]

    assert outcome.resolved
    assert outcome.value.normalized.to_wire() == chosen.normalized.to_wire()
    assert analysis.ai_assisted_fields == 1, "duplicate entries were counted twice"


def test_c2_assisted_count_is_unique_fields_not_entries():
    config = _ai_config()
    snapshot, registries, alternatives = _alternatives(config)

    single = _run(config, registries, snapshot, _model_returning([alternatives[0]]))
    assert single.ai_assisted_fields == 1

    conflicting = _run(config, registries, snapshot, _model_returning(list(alternatives)))
    assert conflicting.ai_assisted_fields == 0


def test_c2_a_field_both_proposed_and_disclaimed_is_not_used():
    """An internally inconsistent response does not silently resolve a field."""
    config = _ai_config()
    snapshot, registries, alternatives = _alternatives(config)

    analysis = _run(config, registries, snapshot,
                    _model_returning([alternatives[0]], unresolved=["gross_weight_kg"]))
    outcome = analysis.bl_fields["gross_weight_kg"]

    assert not outcome.resolved
    assert analysis.ai_assisted_fields == 0


def test_c2_occurring_in_the_document_is_not_being_the_intended_value():
    """Both readings are genuinely present; presence alone does not disambiguate."""
    config = _ai_config()
    snapshot, registries, alternatives = _alternatives(config)
    values = {c.normalized.to_wire() for c in alternatives}
    assert len(values) >= 2, "the fixture no longer has competing readings"

    analysis = _run(config, registries, snapshot, _model_returning(list(alternatives)))
    outcome = analysis.bl_fields["gross_weight_kg"]
    assert outcome.cause is not None
    # The competing readings are retained for the person who must choose.
    retained = {c.normalized.to_wire() for c in outcome.alternatives if c.normalized}
    assert values <= retained


