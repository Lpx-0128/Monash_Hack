"""Normalization and comparison policies (handoff cases A-22 to A-28)."""

from decimal import Decimal

import pytest

from backend.intelligence.normalization import (
    detect_corpus_convention,
    detect_document_convention,
    is_missing_value,
    normalize_party,
    normalize_port,
    parse_container_count,
    parse_gross_weight,
    parse_number,
)
from backend.intelligence.policies import ports as port_policy
from backend.intelligence.types import ContractViolation, NormalizedValue


# --- A-22 container counts -------------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("6 x 40'HC", 6),
    ("3 × 40HC", 3),
    ("3X20'GP", 3),
    ("3 x 40’HC", 3),          # typographic apostrophe from PDF extraction
    ("2 x 20GP + 1 x 40HC", 3),     # disjoint terms are summed
    ("15 x 20'FCL", 15),
])
def test_a22_container_counts_are_derived_correctly(raw, expected):
    parsed = parse_container_count(raw)
    assert parsed.ok and parsed.value == expected


def test_a22_size_is_never_read_as_the_count():
    """40 in `3 x 40'HC` is a size; the count is 3."""
    assert parse_container_count("3 x 40'HC").value == 3
    assert parse_container_count("1 x 20'GP").value == 1


def test_a22_packages_are_not_converted_into_containers():
    """Under a 'Containers or Packages' heading a bare number needs container context."""
    ambiguous = parse_container_count("500", label_is_ambiguous=True)
    assert not ambiguous.ok
    assert ambiguous.ambiguous
    assert ambiguous.reason == "NO_CONTAINER_CONTEXT"
    # The same value under an unambiguous container label is a count.
    assert parse_container_count("500", label_is_ambiguous=False).value == 500
    # Container context under the ambiguous heading resolves it.
    assert parse_container_count("500 x 20'GP", label_is_ambiguous=True).value == 500


@pytest.mark.parametrize("raw", ["0", "-4", "abc", ""])
def test_a25_invalid_counts_produce_no_value(raw):
    assert not parse_container_count(raw).ok


# --- A-23 numeric punctuation ---------------------------------------------

@pytest.mark.parametrize("raw,expected", [
    ("1234", Decimal("1234")),
    ("1,234.50", Decimal("1234.50")),
    ("1.234,50", Decimal("1234.50")),
    ("1,234,567", Decimal("1234567")),
    ("12.5", Decimal("12.5")),
])
def test_a23_unambiguous_notation_parses_exactly(raw, expected):
    parsed = parse_number(raw)
    assert parsed.ok and parsed.value == expected


@pytest.mark.parametrize("raw", ["1,234", "1.234", "131,058"])
def test_a23_a_lone_separator_stays_ambiguous_without_a_convention(raw):
    """Guessing is refused: 1,234 could be 1234 or 1.234."""
    parsed = parse_number(raw, policy="auto", convention="")
    assert not parsed.ok
    assert parsed.ambiguous
    assert parsed.reason == "LONE_SEPARATOR_AMBIGUOUS"


def test_a23_an_established_convention_resolves_a_lone_separator():
    assert parse_number("1,234", policy="auto", convention="en").value == Decimal("1234")
    assert parse_number("1,234", policy="auto", convention="eu").value == Decimal("1.234")


def test_malformed_grouping_is_rejected_rather_than_repaired():
    assert parse_number("1,23,456").reason == "MALFORMED_SEPARATORS"


def test_document_convention_needs_unambiguous_evidence():
    assert detect_document_convention("Total Amount: USD 22,500.00") == "en"
    assert detect_document_convention("Betrag: 22.500,00") == "eu"
    # One lone separator establishes nothing.
    assert detect_document_convention("Gross Weight: 131,058 KG") == ""


def test_corpus_convention_requires_repeated_evidence_and_no_contradiction():
    strong = ["1,234.00", "9,876.50", "2,000,000"]
    assert detect_corpus_convention(strong) == "en"
    # Below the threshold, nothing is adopted.
    assert detect_corpus_convention(["1,234.00"]) == ""
    # Contradictory evidence stays conservative.
    assert detect_corpus_convention(["1,234.00", "9,876.50", "2,000,000",
                                     "1.234,00", "9.876,50", "2.000.000"]) == ""


# --- A-24 units ------------------------------------------------------------

def test_a24_kilograms_and_explicit_tonnes():
    assert parse_gross_weight("21707 KG").value == Decimal("21707")
    assert parse_gross_weight("138 MT").value == Decimal("138000")
    assert parse_gross_weight("1.5 tonnes").value == Decimal("1500.0")


def test_a24_a_unit_may_come_from_the_heading_and_is_cited():
    parsed = parse_gross_weight("341715", label="Gross Wt (kgs)", label_kg=True)
    assert parsed.value == Decimal("341715")
    assert parsed.unit_from_label is True


def test_a24_no_unit_anywhere_is_never_assumed_to_be_kilograms():
    """The field name gross_weight_kg does not supply a missing unit."""
    parsed = parse_gross_weight("341715")
    assert parsed.value is None
    assert parsed.ambiguous
    assert parsed.reason == "MISSING_UNIT"


def test_a24_bare_tons_remain_ambiguous():
    parsed = parse_gross_weight("5 tons")
    assert parsed.value is None and parsed.ambiguous
    assert parsed.reason == "AMBIGUOUS_UNIT"


@pytest.mark.parametrize("raw", ["0 KG", "-5 KG", "NaN KG", "Infinity KG"])
def test_a25_invalid_masses_produce_no_comparable_value(raw):
    assert parse_gross_weight(raw).value is None


def test_a25_the_wire_conversion_refuses_unsupported_precision():
    """A value that cannot round-trip through a JSON number is refused, not rounded."""
    huge = NormalizedValue.of_integer(Decimal(2 ** 53))
    with pytest.raises(ContractViolation):
        huge.to_wire()
    precise = NormalizedValue.of_decimal(Decimal("1.12345678901234567890123"))
    with pytest.raises(ContractViolation):
        precise.to_wire()
    # An ordinary weight converts cleanly.
    assert NormalizedValue.of_decimal(Decimal("21707.5")).to_wire() == 21707.5
    assert NormalizedValue.of_integer(Decimal(6)).to_wire() == 6


# --- A-26, A-27 parties ----------------------------------------------------

@pytest.mark.parametrize("raw", ["", "   ", "N/A", "n/a", "_______", "---", "TBA", "NIL"])
def test_a26_placeholders_count_as_missing(raw):
    assert is_missing_value(raw)


def test_legitimate_text_is_not_treated_as_missing():
    assert not is_missing_value("TO ORDER")
    assert not is_missing_value("0")


def test_a27_a_differing_address_is_preserved_as_a_difference():
    """Name equality does not erase an address difference."""
    left = normalize_party("MERIDIAN TRADING GMBH\nHAFENSTRASSE 44; 20457 HAMBURG")
    right = normalize_party("MERIDIAN TRADING GMBH\nHAFENSTRASSE 99; 20457 HAMBURG")
    assert left != right


def test_party_normalization_keeps_qualifiers_and_never_reorders():
    text = normalize_party("APRIL FINE PAPER TRADING\n  ON BEHALF OF VITAL SOLUTIONS PTE LTD")
    assert "on behalf of" in text
    assert "vital solutions pte ltd" in text
    # Only whitespace and case are normalized.
    assert normalize_party("  ACME  LTD.  ") == "acme ltd"


def test_no_fuzzy_similarity_merges_two_companies():
    assert normalize_party("ACME SHIPPING LTD") != normalize_party("ACME SHIPPING LLC")


# --- A-28 ports ------------------------------------------------------------

def test_a28_a_consistent_port_code_is_supplementary():
    """A code whose country matches the named country may differ in spelling only."""
    assert port_policy.equal("NHAVA SHEVA, INDIA", "NHAVA SHEVA, INDIA (INNSA)")
    assert port_policy.equal("SINGAPORE (SGSIN)", "SINGAPORE")


def test_a28_an_inconsistent_port_code_is_a_real_difference():
    """BALTIMORE, US (NGAPP) names a Nigerian code: that is a defect, not formatting."""
    assert port_policy.code_consistency("BALTIMORE, US (NGAPP)") == port_policy.INCONSISTENT
    assert not port_policy.equal("BALTIMORE, US (USBAL)", "BALTIMORE, US (NGAPP)")
    assert not port_policy.equal("BUATAN, INDONESIA (IDBUA)", "BUATAN, INDONESIA (INNSA)")


def test_a28_terminal_qualifiers_are_never_stripped():
    assert not port_policy.equal("PORT KLANG (WESTPORT), MALAYSIA",
                                 "PORT KLANG (NORTHPORT), MALAYSIA")
    assert "westport" in normalize_port("PORT KLANG (WESTPORT), MALAYSIA")


def test_a28_alternatives_are_not_collapsed_to_the_other_document():
    """RUGAO/NANTONG/SHANGHAI expresses alternatives, not agreement with NANTONG."""
    assert not port_policy.equal("NANTONG, CHINA (CNNTG)",
                                 "RUGAO/NANTONG/SHANGHAI, CHINA (CNSHA)")


def test_port_normalization_is_case_and_space_insensitive_only():
    assert normalize_port("  singapore   (SGSIN) ") == normalize_port("SINGAPORE (SGSIN)")
