"""G1, G2 and G3 (handoff cases A-19 to A-21)."""

import dataclasses
from decimal import Decimal

import pytest

from backend.intelligence.extraction import collect_candidates, resolve_references
from backend.intelligence.grounding import check_g1, check_g2, check_g3, ground_candidate
from backend.intelligence.types import (
    Candidate,
    Derivation,
    Evidence,
    ExtractionMethod,
    NormalizedValue,
    PdfPage,
    TextRange,
)

SOURCE = (
    "SHIPPING INSTRUCTION\n"
    "Shipper: NORTHWIND PAPER EXPORTS PTE LTD\n"
    "Consignee: MERIDIAN TRADING GMBH\n"
    "Notify Party: SAME AS CONSIGNEE\n"
    "Seal No.: 18500\n"
    "NET WEIGHT: 18500 KG\n"
    "Gross Weight (KG): 21600 KG\n"
    "Total Containers: 4 x 40'HC\n"
)


@pytest.fixture
def document(parse):
    return parse(SOURCE.encode("utf-8"), document_id="si_doc")


@pytest.fixture
def candidates(document):
    return resolve_references(collect_candidates(document, "SI"))


def _one(candidates, field):
    return next(c for c in candidates[field] if c.normalized is not None
                or c.derivation is Derivation.REFERENCE)


def test_real_candidates_pass_all_three_gates(document, candidates):
    references = {"consignee": _one(candidates, "consignee").normalized}
    for field in ("shipper", "consignee", "port_of_loading" if candidates["port_of_loading"]
                  else "container_count", "gross_weight_kg", "container_count"):
        for candidate in candidates[field]:
            if candidate.normalized is None:
                continue
            result = ground_candidate(candidate, document, expected_hash=document.content_hash,
                                      reference_values=references)
            assert result.passed, f"{field}: {result.gate} {result.reason}"


def test_a19_a_fabricated_quote_fails_g1(document, candidates):
    good = _one(candidates, "shipper")
    forged = dataclasses.replace(
        good, evidence=(Evidence("si_doc", good.evidence[0].locator, "ACME CORPORATION"),)
    )
    result = check_g1(forged, document)
    assert not result.passed and result.reason == "QUOTE_MISMATCH"


def test_a19_a_stale_artifact_hash_fails_g1(document, candidates):
    good = _one(candidates, "shipper")
    result = check_g1(good, document, expected_hash="0" * 64)
    assert not result.passed and result.reason == "STALE_ARTIFACT"


def test_a19_another_document_fails_g1(document, candidates):
    good = _one(candidates, "shipper")
    other = dataclasses.replace(good, document_id="bl_doc")
    result = check_g1(other, document)
    assert not result.passed and result.reason == "WRONG_DOCUMENT"


def test_a19_an_out_of_bounds_locator_fails_g1(document, candidates):
    good = _one(candidates, "shipper")
    bogus = dataclasses.replace(
        good, evidence=(Evidence("si_doc", TextRange(10 ** 6, 10 ** 6 + 5), "ACME"),)
    )
    result = check_g1(bogus, document)
    assert not result.passed and result.reason == "LOCATOR_NOT_FOUND"


def test_a19_a_wrong_page_fails_g1(parse_demo):
    document = parse_demo("demo_pdf_BL.pdf", document_id="pdf_doc")
    candidate = Candidate(
        field="shipper", side="BL", document_id="pdf_doc",
        raw="NORTHWIND PAPER EXPORTS PTE LTD", label_text="SHIPPER",
        evidence=(Evidence("pdf_doc", PdfPage(9), "NORTHWIND PAPER EXPORTS PTE LTD"),),
        normalized=NormalizedValue.of_text("northwind paper exports pte ltd"),
    )
    result = check_g1(candidate, document)
    assert not result.passed and result.reason == "LOCATOR_NOT_FOUND"


def test_a20_matching_digits_in_a_seal_field_fail_g2(document):
    """A-20: 18500 appears in Seal No. and NET WEIGHT; neither supports gross weight."""
    for label in ("Seal No.", "NET WEIGHT"):
        block = next(b for b in document.blocks if b.label == label)
        candidate = Candidate(
            field="gross_weight_kg", side="SI", document_id="si_doc",
            raw=block.value_text, label_text=label,
            evidence=(Evidence("si_doc", block.value_locator, block.value_text),),
            normalized=NormalizedValue.of_decimal(Decimal("18500")),
        )
        assert check_g1(candidate, document).passed, label
        result = check_g2(candidate, document)
        assert not result.passed, f"{label} wrongly supported a gross weight"
        assert result.reason in ("NEGATIVE_LABEL", "LABEL_DOES_NOT_SUPPORT_FIELD")


def test_a20_the_same_rejection_applies_to_a_human_proposal(document):
    """G2 is shared: a person cannot confirm a seal number as a gross weight."""
    from backend.intelligence.recomputation import find_document_support

    supported = find_document_support(
        "gross_weight_kg", "SI", document,
        NormalizedValue.of_decimal(Decimal("18500")), policy="auto", convention="",
    )
    # 18500 only appears under a seal and a net weight label.
    assert supported is None


def test_a20_a_value_with_no_label_fails_g2(document, candidates):
    good = _one(candidates, "shipper")
    unlabelled = dataclasses.replace(good, label_text=None)
    result = check_g2(unlabelled, document)
    assert not result.passed and result.reason == "NO_LABEL"


def test_a21_a_wrong_normalized_value_fails_g3(document, candidates):
    """A-21: the quote is real but the proposed canonical value is not derivable."""
    good = _one(candidates, "gross_weight_kg")
    wrong = good.with_normalized(NormalizedValue.of_decimal(Decimal("99999")))
    assert check_g1(wrong, document).passed
    assert check_g2(wrong, document).passed
    result = check_g3(wrong, document)
    assert not result.passed and result.reason == "WEIGHT_MISMATCH"


def test_a21_a_wrong_party_normalization_fails_g3(document, candidates):
    good = _one(candidates, "shipper")
    wrong = good.with_normalized(NormalizedValue.of_text("some other company"))
    result = check_g3(wrong, document)
    assert not result.passed and result.reason == "PARTY_DERIVATION_MISMATCH"


def test_a21_a_wrong_count_fails_g3(document, candidates):
    good = _one(candidates, "container_count")
    wrong = good.with_normalized(NormalizedValue.of_integer(Decimal(40)))
    result = check_g3(wrong, document)
    assert not result.passed and result.reason == "COUNT_MISMATCH"


def test_a29_same_as_consignee_retains_both_evidence_sets(document, candidates):
    """A-29: the reference wording and the consignee's own evidence are both kept."""
    notify = _one(candidates, "notify_party")
    consignee = _one(candidates, "consignee")

    assert notify.derivation is Derivation.REFERENCE
    assert notify.reference_field == "consignee"
    assert notify.normalized.equals(consignee.normalized)

    quotes = {evidence.source_text.strip() for evidence in notify.evidence}
    assert "SAME AS CONSIGNEE" in quotes
    assert "MERIDIAN TRADING GMBH" in quotes

    result = ground_candidate(notify, document,
                              reference_values={"consignee": consignee.normalized})
    assert result.passed


def test_a29_a_reference_to_a_different_value_fails_g3(document, candidates):
    notify = _one(candidates, "notify_party")
    result = check_g3(notify, document,
                      reference_values={"consignee": NormalizedValue.of_text("other gmbh")})
    assert not result.passed and result.reason == "REFERENCE_MISMATCH"


def test_grounded_true_cannot_simply_be_asserted(document):
    """A caller cannot supply evidence-free support for a value."""
    candidate = Candidate(
        field="shipper", side="SI", document_id="si_doc", raw="ACME",
        label_text="Shipper", evidence=(),
        normalized=NormalizedValue.of_text("acme"),
    )
    result = ground_candidate(candidate, document)
    assert not result.passed and result.reason == "NO_EVIDENCE"
