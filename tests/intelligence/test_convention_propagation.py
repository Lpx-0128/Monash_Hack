"""A registry-level numeric convention must reach extraction *and* grounding.

Review §5 asked for this before the source-convention setting is described as
equivalent to the explicit locale policy. On 58f2a7e it was not: extraction
received ``fallback_convention`` and resolved the value, but G3 re-derived using
only the document-local convention, so the field came back ``UNGROUNDED`` —
worse than either policy alone.
"""

import json

import pytest

from backend.intelligence.config import load_config
from backend.intelligence.grounding import check_g3
from backend.intelligence.ingestion import SourceRegistry, build_registries, ingest_case
from backend.intelligence.pipeline import (
    AnalysisContext,
    IntelligenceServices,
    analyze_case,
)
from backend.intelligence.types import UncertaintyCause

SI = (
    "SHIPPING INSTRUCTION\n"
    "Shipper: NORTHWIND PAPER EXPORTS PTE LTD\n"
    "Consignee: MERIDIAN TRADING GMBH\n"
    "Notify Party: MERIDIAN TRADING GMBH\n"
    "Port of Loading (POL): SINGAPORE\n"
    "Port of Discharge (POD): HAMBURG, GERMANY\n"
    "Total Containers: 4 x 40'HC\n"
    "Gross Weight (KG): 18,500 KG\n"
)
BL = SI.replace("SHIPPING INSTRUCTION", "BILL OF LADING (DRAFT)")


def _registry(tmp_path, *, with_convention_evidence: bool):
    """A registry whose case documents carry only a lone separator."""
    root = tmp_path / "registry"
    (root / "inbox").mkdir(parents=True)
    (root / "attachments").mkdir()
    (root / "attachments" / "c_SI.txt").write_text(SI, encoding="utf-8")
    (root / "attachments" / "c_BL.txt").write_text(BL, encoding="utf-8")
    if with_convention_evidence:
        # Repeated unambiguous en-form values elsewhere in the registry.
        for index in range(4):
            (root / "attachments" / f"evidence_{index}.txt").write_text(
                f"Total Amount: USD {index + 1},234.5{index}\n", encoding="utf-8"
            )
    (root / "inbox" / "email_conv.json").write_text(json.dumps({
        "email_id": "email_conv", "from": "sender@example.invalid",
        "subject": "Please check SI vs draft BL",
        "body": "Please compare the SI and draft BL and confirm.",
        "attachments": ["attachments/c_SI.txt", "attachments/c_BL.txt"],
    }), encoding="utf-8")
    return SourceRegistry("participant", root, demo_safe=False)


def _analyze(registry, config):
    registries = {"participant": registry,
                  "synthetic_demo": build_registries(config)["synthetic_demo"]}
    snapshot = ingest_case("email_conv", namespace="EVAL", case_id="email_conv",
                           registries=registries, config=config)
    context = AnalysisContext("email_conv", "run_conv", "EVAL", config,
                              lambda: "2026-09-21T00:00:00Z", lambda p: f"{p}_1")
    return analyze_case(snapshot, context, IntelligenceServices(registries=registries))


def test_a_registry_convention_resolves_the_value_end_to_end(tmp_path):
    """Extraction and grounding agree, so the field is usable, not ungrounded."""
    config = load_config()
    registry = _registry(tmp_path, with_convention_evidence=True)
    assert registry.numeric_convention() == "en"

    analysis = _analyze(registry, config)
    outcome = analysis.si_fields["gross_weight_kg"]

    assert outcome.resolved, f"convention did not propagate: {outcome.cause} {outcome.detail}"
    assert outcome.value.normalized.to_wire() == 18500
    assert outcome.cause is None
    assert analysis.assessment.status == "OK"


def test_without_registry_evidence_the_value_stays_honestly_ambiguous(tmp_path):
    """No convention means no guess — and specifically not a grounding failure."""
    config = load_config()
    registry = _registry(tmp_path, with_convention_evidence=False)
    assert registry.numeric_convention() == ""

    analysis = _analyze(registry, config)
    outcome = analysis.si_fields["gross_weight_kg"]

    assert not outcome.resolved
    # Ambiguity, not a grounding defect.
    assert outcome.cause is UncertaintyCause.AMBIGUOUS_SEPARATOR
    assert analysis.assessment.status == "NEEDS_REVIEW"


def test_g3_uses_the_same_convention_extraction_used(tmp_path):
    """The gate must not reject what extraction legitimately resolved."""
    config = load_config()
    registry = _registry(tmp_path, with_convention_evidence=True)
    analysis = _analyze(registry, config)

    outcome = analysis.si_fields["gross_weight_kg"]
    document = analysis.parsed[outcome.value.document_id]

    # With the registry convention, the derivation reproduces.
    assert check_g3(outcome.value, document, policy=config.numeric_locale_policy,
                    fallback_convention="en").passed
    # Without it, the same value is not derivable — which is exactly the
    # mismatch that produced UNGROUNDED before.
    assert not check_g3(outcome.value, document, policy=config.numeric_locale_policy,
                        fallback_convention="").passed


def test_an_explicit_locale_policy_and_a_registry_convention_agree(tmp_path):
    """The two routes to a convention produce the same canonical value."""
    import dataclasses

    registry_route = _analyze(_registry(tmp_path / "a", with_convention_evidence=True),
                              load_config())
    explicit = dataclasses.replace(load_config(), numeric_locale_policy="en")
    policy_route = _analyze(_registry(tmp_path / "b", with_convention_evidence=False),
                            explicit)

    left = registry_route.si_fields["gross_weight_kg"]
    right = policy_route.si_fields["gross_weight_kg"]
    assert left.resolved and right.resolved
    assert left.value.normalized.to_wire() == right.value.normalized.to_wire() == 18500
