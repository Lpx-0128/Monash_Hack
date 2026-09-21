"""Document roles and the assessment roll-up (handoff cases A-09, A-10, A-26, A-30 to A-34)."""

from decimal import Decimal

import pytest

from backend.intelligence.comparison import compare_all, compare_field, roll_up
from backend.intelligence.extraction import extract_side, resolve_field
from backend.intelligence.roles import filename_hint, resolve_roles
from backend.intelligence.types import (
    Candidate,
    Evidence,
    FieldOutcome,
    NormalizedValue,
    TextRange,
    UncertaintyCause,
)

from .conftest import PARTICIPANT_ROOT

SI_TEXT = (
    "SHIPPING INSTRUCTION\n"
    "Shipper: NORTHWIND PAPER EXPORTS PTE LTD\n"
    "Consignee: MERIDIAN TRADING GMBH\n"
    "Notify Party: MERIDIAN TRADING GMBH\n"
    "Port of Loading (POL): SINGAPORE (SGSIN)\n"
    "Port of Discharge (POD): HAMBURG, GERMANY (DEHAM)\n"
    "Total Containers: 4 x 40'HC\n"
    "Gross Weight (KG): 18500 KG\n"
)


def _bl(**overrides) -> str:
    values = {
        "shipper": "NORTHWIND PAPER EXPORTS PTE LTD",
        "consignee": "MERIDIAN TRADING GMBH",
        "notify": "MERIDIAN TRADING GMBH",
        "pol": "SINGAPORE (SGSIN)",
        "pod": "HAMBURG, GERMANY (DEHAM)",
        "count": "4 x 40'HC",
        "weight": "18500 KG",
    }
    values.update(overrides)
    return (
        "BILL OF LADING (DRAFT)\n"
        f"SHIPPER: {values['shipper']}\n"
        f"Consignee (Non-Negotiable): {values['consignee']}\n"
        f"NOTIFY PARTY: {values['notify']}\n"
        f"Load Port: {values['pol']}\n"
        f"Discharge Port: {values['pod']}\n"
        f"Container Count: {values['count']}\n"
        f"Gross Wt (kgs): {values['weight']}\n"
    )


def _compare(parse, si_text: str, bl_text: str):
    si = parse(si_text.encode("utf-8"), document_id="si")
    bl = parse(bl_text.encode("utf-8"), document_id="bl")
    return compare_all(extract_side(si, "SI"), extract_side(bl, "BL"))


# --- roles -----------------------------------------------------------------

def test_a09_a_bl_filename_holding_an_invoice_is_not_a_bl(parse):
    """A-09: email_501_BL.txt is a commercial invoice."""
    si = parse((PARTICIPANT_ROOT / "attachments" / "email_501_SI.txt").read_bytes(),
               filename="email_501_SI.txt", document_id="si")
    bl = parse((PARTICIPANT_ROOT / "attachments" / "email_501_BL.txt").read_bytes(),
               filename="email_501_BL.txt", document_id="bl")
    hints = {"si": filename_hint("email_501_SI.txt"), "bl": filename_hint("email_501_BL.txt")}

    resolution = resolve_roles([si, bl], hints)
    assert resolution.si == "si"
    assert resolution.bl is None            # the filename hint did not win
    assert "BL_WRONG_DOC_TYPE" in resolution.issues


def test_a09_a_negated_heading_is_not_a_positive_signal(parse):
    text = ("PACKING LIST\n"
            "*** THIS IS NOT A SHIPPING INSTRUCTION ***\n"
            "Total Packages: 820 CARTONS\n")
    document = parse(text.encode("utf-8"), document_id="pl")
    resolution = resolve_roles([document], {})
    assert resolution.si is None


def test_a10_two_plausible_drafts_are_kept_as_alternatives(parse):
    """A-10: a tie is a question, not an arbitrary pick of the first attachment."""
    si = parse(SI_TEXT.encode("utf-8"), document_id="si")
    rev1 = parse(_bl().encode("utf-8"), document_id="bl1")
    rev2 = parse(_bl(count="5 x 40'HC").encode("utf-8"), document_id="bl2")

    resolution = resolve_roles([si, rev1, rev2], {})
    assert resolution.bl is None
    assert set(resolution.bl_alternatives) == {"bl1", "bl2"}
    assert "BL_ROLE_UNRESOLVED" in resolution.issues


def test_a_document_never_occupies_both_roles(parse):
    si = parse(SI_TEXT.encode("utf-8"), document_id="si")
    bl = parse(_bl().encode("utf-8"), document_id="bl")
    resolution = resolve_roles([si, bl], {})
    assert resolution.si != resolution.bl


def test_bill_of_lading_instruction_is_an_si(parse):
    """A heading naming both must not be read as a bill of lading."""
    text = SI_TEXT.replace("SHIPPING INSTRUCTION", "BILL OF LADING INSTRUCTION")
    document = parse(text.encode("utf-8"), document_id="si")
    resolution = resolve_roles([document], {})
    assert resolution.si == "si"
    assert resolution.bl is None


# --- comparison ------------------------------------------------------------

def test_a31_a_grounded_difference_is_a_deterministic_mismatch(parse):
    """A-31: a clear difference needs no human question."""
    comparisons = _compare(parse, SI_TEXT, _bl(consignee="ORION IMPORTS SARL"))
    assessment = roll_up("BL_COMPARISON", comparisons)
    assert assessment.status == "MISMATCH"
    assert assessment.defect_fields == ("consignee",)
    assert assessment.has_defect is True
    assert assessment.review_reason is None
    consignee = next(c for c in comparisons if c.field == "consignee")
    assert consignee.compared_by == "DETERMINISTIC"


def test_all_seven_matching_is_ok(parse):
    comparisons = _compare(parse, SI_TEXT, _bl())
    assert all(c.result == "MATCH" for c in comparisons)
    assessment = roll_up("BL_COMPARISON", comparisons)
    assert assessment.status == "OK"
    assert assessment.defect_fields == ()
    assert assessment.has_defect is False


def test_a32_a_mismatch_stays_visible_when_needs_review_takes_precedence(parse):
    """A-32: container counts differ while the SI weight is missing."""
    si = SI_TEXT.replace("Gross Weight (KG): 18500 KG", "Gross Weight (KG): N/A")
    comparisons = _compare(parse, si, _bl(count="5 x 40'HC"))
    assessment = roll_up("BL_COMPARISON", comparisons)

    assert assessment.status == "NEEDS_REVIEW"
    assert assessment.review_reason == "missing_value"
    # The exported defect list is empty, but the working table keeps the truth.
    assert assessment.has_defect is False
    assert assessment.defect_fields == ()
    container = next(c for c in comparisons if c.field == "container_count")
    assert container.result == "MISMATCH"


def test_a26_two_blank_values_are_never_a_match(parse):
    """A-26: absent on both sides is NOT_COMPARABLE, not agreement."""
    si = SI_TEXT.replace("Gross Weight (KG): 18500 KG", "Gross Weight (KG): N/A")
    comparisons = _compare(parse, si, _bl(weight="N/A"))
    weight = next(c for c in comparisons if c.field == "gross_weight_kg")
    assert weight.result == "NOT_COMPARABLE"
    assert weight.not_comparable_cause == "MISSING_VALUE"


def test_not_comparable_iff_a_cause_is_present(parse):
    comparisons = _compare(parse, SI_TEXT, _bl(weight="N/A"))
    for comparison in comparisons:
        if comparison.result == "NOT_COMPARABLE":
            assert comparison.not_comparable_cause is not None
        else:
            assert comparison.not_comparable_cause is None


def test_a33_a_non_bl_category_settles_ok_with_no_fields():
    """A-33: no comparison, no defects, no review."""
    assessment = roll_up("INVOICE_QUERY", ())
    assert assessment.status == "OK"
    assert assessment.review_reason is None
    assert assessment.has_defect is False
    assert assessment.defect_fields == ()


def test_a30_a_total_conflicting_with_another_labelled_value_stays_unresolved(parse):
    """A-30: a declared total that disagrees is a conflict, not a silent choice."""
    text = (SI_TEXT
            + "TOTAL Gross Weight (KG): 99999 KG\n")
    document = parse(text.encode("utf-8"), document_id="si")
    outcome = extract_side(document, "SI")["gross_weight_kg"]
    assert not outcome.resolved
    assert outcome.cause is UncertaintyCause.COMPETING_CANDIDATES
    assert len(outcome.alternatives) >= 2


def test_a30_a_total_agreeing_with_its_components_is_counted_once(parse_demo):
    """A-30: the PDF's three 7200 rows are never added to its 21600 total."""
    document = parse_demo("demo_pdf_BL.pdf", document_id="bl")
    outcome = extract_side(document, "BL")["gross_weight_kg"]
    assert outcome.resolved
    assert outcome.value.normalized.to_wire() == 21600


def test_a34_two_individually_grounded_candidates_leave_the_field_ambiguous(parse):
    """A-34: evidence for one value does not erase evidence for the other."""
    text = SI_TEXT + "Gross Wt (kgs): 17000 KG\n"
    document = parse(text.encode("utf-8"), document_id="si")
    outcome = extract_side(document, "SI")["gross_weight_kg"]
    assert not outcome.resolved
    assert outcome.cause is UncertaintyCause.COMPETING_CANDIDATES
    values = {c.normalized.to_wire() for c in outcome.alternatives if c.normalized}
    assert values == {18500, 17000}


def test_roll_up_precedence_document_problem_beats_field_uncertainty(parse):
    comparisons = _compare(parse, SI_TEXT, _bl(weight="N/A"))
    assessment = roll_up("BL_COMPARISON", comparisons, ("BL_MISSING",))
    assert assessment.status == "NEEDS_REVIEW"
    assert assessment.review_reason == "missing_attachment"


def test_reason_priority_picks_the_most_severe(parse):
    comparisons = _compare(parse, SI_TEXT, _bl())
    assessment = roll_up("BL_COMPARISON", comparisons,
                         ("BL_UNREADABLE", "SI_MISSING", "SI_WRONG_DOC_TYPE"))
    assert assessment.review_reason == "missing_attachment"


def test_human_provenance_does_not_make_the_comparison_human():
    """Exact equality is deterministic even when a person supplied one side."""
    from backend.intelligence.types import ExtractionMethod

    def value(method):
        return FieldOutcome(
            field="container_count", side="SI",
            value=Candidate(
                field="container_count", side="SI", document_id="d", raw="4",
                label_text="Container Count",
                evidence=(Evidence("d", TextRange(0, 1), "4"),),
                method=method, normalized=NormalizedValue.of_integer(Decimal(4)),
            ),
        )

    result = compare_field("container_count", value(ExtractionMethod.HUMAN),
                           value(ExtractionMethod.RULE))
    assert result.result == "MATCH"
    assert result.compared_by == "DETERMINISTIC"
