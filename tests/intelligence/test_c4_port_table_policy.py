"""C4 regression: strict majority, and honest provenance for the port table.

On 675f0d3 ``derive`` accepted a 3/2/2 distribution as a "strict majority" — it
only checked the minimum count and a first-place tie. The table was also called
"verified", though it is a convention learned from the development corpus, not
an externally validated mapping.
"""

import collections
import sys

import pytest

from backend.intelligence.policies import ports as port_policy

sys.path.insert(0, "scripts")
from derive_port_codes import MIN_OBSERVATIONS, derive  # noqa: E402

def _counts(mapping):
    return {"a port": collections.Counter(mapping)}


def test_c4_three_of_seven_is_not_a_strict_majority():
    """The reviewer's exact distribution."""
    table, rejected = derive(_counts({"AAAAA": 3, "BBBBB": 2, "CCCCC": 2}), MIN_OBSERVATIONS)
    assert table == {}
    assert rejected[0]["reason"] == "not a strict majority"


def test_c4_an_actual_majority_is_accepted():
    table, rejected = derive(_counts({"AAAAA": 5, "BBBBB": 2}), MIN_OBSERVATIONS)
    assert table == {"a port": "AAAAA"}
    assert rejected == []


def test_c4_a_tie_is_rejected():
    table, rejected = derive(_counts({"AAAAA": 3, "BBBBB": 3}), MIN_OBSERVATIONS)
    assert table == {}
    assert rejected[0]["reason"] == "evidence is split"


def test_c4_insufficient_evidence_is_rejected():
    table, rejected = derive(_counts({"AAAAA": 2, "BBBBB": 1}), MIN_OBSERVATIONS)
    assert table == {}
    assert rejected[0]["reason"] == "too few observations"


def test_c4_a_plurality_over_many_codes_still_needs_a_majority():
    table, rejected = derive(_counts({"AAAAA": 4, "B": 2, "C": 2, "D": 2}), MIN_OBSERVATIONS)
    assert table == {}
    assert rejected[0]["reason"] == "not a strict majority"


def test_c4_the_shipped_table_satisfies_the_strict_rule():
    from pathlib import Path

    from derive_port_codes import observations

    counts = observations(Path("resources/sdoc-hackathon-bundle"))
    derived, _rejected = derive(counts, MIN_OBSERVATIONS)
    assert derived == port_policy.CORPUS_PORT_CODES
    for place, code in derived.items():
        total = sum(counts[place].values())
        assert counts[place][code] * 2 > total, place


def test_c4_the_table_is_not_described_as_verified():
    """A corpus convention learned from development data is not a verification."""
    assert port_policy.CORPUS_CONVENTION == "corpus_convention"
    assert hasattr(port_policy, "CORPUS_PORT_CODES")
    assert "corpus" in port_policy.__doc__.lower()
    assert "not external validation" in port_policy.__doc__.lower() or \
           "not" in port_policy.__doc__.lower()


def test_c4_the_convention_is_off_until_the_team_approves_it():
    assert port_policy.PORT_TABLE_APPROVED is False
    assert port_policy.supplementary_key("NHAVA SHEVA, INDIA (INNSA)") is None
