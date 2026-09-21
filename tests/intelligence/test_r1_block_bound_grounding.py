"""R1 regression: grounding must not accept another field's value.

On 58f2a7e every value on a PDF page shared ``PdfPage(1)``: G1 proved only that
the quote occurred somewhere on the page, and G2 found the claimed label
anywhere with that same locator. A gross-weight candidate quoting the net
weight passed all three gates. These tests fail on that commit.
"""

import hashlib
from decimal import Decimal

import pytest

from backend.intelligence.grounding import check_g1, check_g2, check_g3, ground_candidate
from backend.intelligence.parsers.router import parse_source
from backend.intelligence.policies import aliases
from backend.intelligence.types import (
    Candidate,
    Evidence,
    NormalizedValue,
    PdfPage,
)


def _pdf(tmp_path, lines, config, document_id="d1"):
    import sys
    sys.path.insert(0, "scripts")
    from build_demo_fixtures import write_text_pdf

    path = tmp_path / f"{document_id}.pdf"
    write_text_pdf(path, lines)
    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    document = parse_source(data, document_id=document_id, content_hash=digest,
                            filename=path.name, media_type="", config=config)
    return document, digest


def _block(document, label):
    return next(b for b in document.blocks if b.label == label)


def _candidate(field, block_id, quote, value, *, document_id="d1",
               label="Gross Weight", locator=None, text=False):
    normalized = (NormalizedValue.of_text(value) if text
                  else NormalizedValue.of_decimal(Decimal(value)))
    return Candidate(
        field=field, side="SI", document_id=document_id, raw=quote, label_text=label,
        evidence=(Evidence(document_id, locator or PdfPage(1), quote),),
        normalized=normalized, block_id=block_id,
    )


@pytest.fixture
def two_weights(tmp_path, config):
    return _pdf(tmp_path, ["Gross Weight: 21600 KG", "Net Weight: 18500 KG"], config)


def test_r1_gross_weight_candidate_quoting_the_net_weight_is_rejected(two_weights):
    """The exact scenario from the review: same page, same document, real hash."""
    document, digest = two_weights
    gross = _block(document, "Gross Weight")

    forged = _candidate("gross_weight_kg", gross.block_id, "18500 KG", "18500")
    result = ground_candidate(forged, document, expected_hash=digest)

    assert not result.passed, "a net-weight quote was accepted as a gross weight"
    assert result.gate == "G1"
    assert result.reason == "QUOTE_MISMATCH"


def test_r1_binding_to_the_net_weight_block_is_rejected_by_g2(two_weights):
    """Claiming a gross-weight label over a net-weight block does not help."""
    document, digest = two_weights
    net = _block(document, "Net Weight")

    forged = _candidate("gross_weight_kg", net.block_id, "18500 KG", "18500")
    assert check_g1(forged, document, expected_hash=digest).passed
    result = check_g2(forged, document)

    assert not result.passed
    assert result.reason == "NEGATIVE_LABEL"


def test_r1_an_unbound_candidate_cannot_be_grounded(two_weights):
    """A candidate that names no block proves nothing, whatever it claims."""
    document, digest = two_weights
    forged = _candidate("gross_weight_kg", None, "18500 KG", "18500")
    result = ground_candidate(forged, document, expected_hash=digest)
    assert not result.passed and result.reason == "NO_BOUND_BLOCK"


def test_r1_a_seal_number_with_matching_digits_is_rejected(tmp_path, config):
    """Digits that happen to match, sitting in a seal field, are not a weight."""
    document, digest = _pdf(tmp_path, [
        "Gross Weight: 21600 KG",
        "Seal No.: 21600",
    ], config)
    seal = _block(document, "Seal No.")

    forged = _candidate("gross_weight_kg", seal.block_id, "21600", "21600")
    result = ground_candidate(forged, document, expected_hash=digest)
    assert not result.passed
    assert result.gate == "G2"


def test_r1_two_values_on_one_page_do_not_cross_contaminate(tmp_path, config):
    """Each labelled value grounds only against its own block."""
    document, digest = _pdf(tmp_path, [
        "Port of Loading: SINGAPORE",
        "Port of Discharge: HAMBURG",
    ], config)
    loading = _block(document, "Port of Loading")

    swapped = _candidate("port_of_loading", loading.block_id, "HAMBURG", "hamburg",
                         label="Port of Loading", text=True)
    result = ground_candidate(swapped, document, expected_hash=digest)
    assert not result.passed and result.gate == "G1"


def test_r1_multiple_labels_in_one_paragraph_do_not_cross_contaminate(parse):
    """A shared docx_paragraph locator is not proof of a label/value pairing."""
    source = "Gross Weight (KG): 21600 KG\nNET WEIGHT: 18500 KG\n"
    document = parse(source.encode("utf-8"), document_id="txt_doc")
    gross = next(b for b in document.blocks if aliases.match_field(b.label) == "gross_weight_kg")

    forged = Candidate(
        field="gross_weight_kg", side="SI", document_id="txt_doc", raw="18500 KG",
        label_text="Gross Weight (KG)",
        evidence=(Evidence("txt_doc", gross.value_locator, "18500 KG"),),
        normalized=NormalizedValue.of_decimal(Decimal("18500")),
        block_id=gross.block_id,
    )
    result = ground_candidate(forged, document, expected_hash=document.content_hash)
    assert not result.passed


def test_r1_legitimate_extraction_still_grounds(two_weights):
    """The fix must not reject real values."""
    document, digest = two_weights
    gross = _block(document, "Gross Weight")
    good = _candidate("gross_weight_kg", gross.block_id, "21600 KG", "21600")
    assert ground_candidate(good, document, expected_hash=digest).passed


def test_r1_every_pipeline_candidate_is_block_bound(parse_demo):
    """Rule extraction binds every candidate it produces."""
    from backend.intelligence.extraction import collect_candidates, resolve_references

    document = parse_demo("demo_match_SI.txt", document_id="si")
    by_field = resolve_references(collect_candidates(document, "SI"))
    produced = [c for candidates in by_field.values() for c in candidates]
    assert produced
    for candidate in produced:
        assert candidate.block_id is not None, candidate.field
        assert document.block_by_id(candidate.block_id) is not None


def test_r1_g3_rederives_from_the_block_not_the_supplied_quote(two_weights):
    """A caller cannot choose the text its value is checked against."""
    document, digest = two_weights
    gross = _block(document, "Gross Weight")

    # Quote and value agree with each other, but not with the bound block.
    lying = _candidate("gross_weight_kg", gross.block_id, "18500 KG", "18500")
    assert not check_g1(lying, document, expected_hash=digest).passed

    # Even with a quote drawn from the right block, a wrong value fails G3.
    wrong_value = _candidate("gross_weight_kg", gross.block_id, "21600 KG", "99999")
    assert check_g1(wrong_value, document, expected_hash=digest).passed
    assert check_g2(wrong_value, document).passed
    result = check_g3(wrong_value, document)
    assert not result.passed and result.reason == "WEIGHT_MISMATCH"


def test_r1_the_defect_shape_itself_is_rejected(two_weights):
    """Built exactly as 58f2a7e allowed — no block binding at all.

    On the reviewed commit this candidate passed G1, G2 and G3: the quote was
    on the page, a gross-weight label existed on that page, and the value parsed
    from the quote. Constructing it with only the fields that existed then, it
    must now be refused.
    """
    document, digest = two_weights

    legacy_shape = Candidate(
        field="gross_weight_kg",
        side="SI",
        document_id="d1",
        raw="18500 KG",
        label_text="Gross Weight",           # claimed, never verified on 58f2a7e
        evidence=(Evidence("d1", PdfPage(1), "18500 KG"),),
        normalized=NormalizedValue.of_decimal(Decimal("18500")),
    )

    result = ground_candidate(legacy_shape, document, expected_hash=digest)
    assert not result.passed, (
        "the reviewed defect is still present: a gross-weight candidate quoting "
        "the net weight was accepted"
    )
