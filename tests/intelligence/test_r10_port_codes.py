"""R10 regression: a port code is supplementary only when the source says so.

On 58f2a7e a code whose country prefix merely matched the named country was
discarded as formatting, so ``PORT KLANG, MALAYSIA (MYZZZ)`` compared equal to
``PORT KLANG, MALAYSIA``. Country agreement is not port identification.
"""

import pytest

from backend.intelligence.policies import ports as port_policy


def test_r10_a_wrong_same_country_code_is_not_discarded():
    """The review's exact case: MYZZZ is Malaysian-prefixed but identifies nothing."""
    assert port_policy.code_state("PORT KLANG, MALAYSIA (MYZZZ)") == port_policy.UNESTABLISHED
    assert not port_policy.equal("PORT KLANG, MALAYSIA", "PORT KLANG, MALAYSIA (MYZZZ)")


def test_r10_an_unknown_code_on_a_known_port_is_a_difference():
    assert port_policy.code_state("SINGAPORE (SGXXX)") == port_policy.CONTRADICTED
    assert not port_policy.equal("SINGAPORE (SGXXX)", "SINGAPORE")
    assert not port_policy.equal("SINGAPORE (SGXXX)", "SINGAPORE (SGSIN)")


def test_r10_the_corpus_convention_is_recognised_but_not_called_verified():
    """The table records what the corpus writes; that is not external validation."""
    assert port_policy.code_state("NHAVA SHEVA, INDIA (INNSA)") == port_policy.CORPUS_CONVENTION
    assert "verified" not in port_policy.CORPUS_CONVENTION


def test_r10_an_unapproved_convention_does_not_discard_a_code(monkeypatch):
    """C4: until the team approves the table, a code difference stays visible."""
    assert port_policy.PORT_TABLE_APPROVED is False
    assert not port_policy.equal("NHAVA SHEVA, INDIA", "NHAVA SHEVA, INDIA (INNSA)")
    assert not port_policy.equal("SINGAPORE (SGSIN)", "SINGAPORE")


def test_r10_approving_the_table_makes_the_convention_supplementary(monkeypatch):
    """With the decision recorded, two spellings of the same port compare equal."""
    monkeypatch.setattr(port_policy, "PORT_TABLE_APPROVED", True)
    assert port_policy.equal("NHAVA SHEVA, INDIA", "NHAVA SHEVA, INDIA (INNSA)")
    assert port_policy.equal("SINGAPORE (SGSIN)", "SINGAPORE")
    # Approval never makes a contradicted code equal.
    assert not port_policy.equal("BALTIMORE, US (USBAL)", "BALTIMORE, US (NGAPP)")


@pytest.mark.parametrize("left,right", [
    ("BALTIMORE, US (USBAL)", "BALTIMORE, US (NGAPP)"),
    ("BUATAN, INDONESIA (IDBUA)", "BUATAN, INDONESIA (INNSA)"),
    ("BUSAN, SOUTH KOREA (KRPUS)", "BUSAN, SOUTH KOREA (AUFRE)"),
    ("LONG BEACH, US (USLGB)", "LONG BEACH, US (TRMER)"),
    ("MOMBASA, KENYA (KEMBA)", "MOMBASA, KENYA (AUBNE)"),
])
def test_r10_two_conflicting_codes_never_compare_equal(left, right):
    """Planted code defects in the corpus stay visible."""
    assert not port_policy.equal(left, right)


def test_r10_a_port_with_thin_or_split_evidence_stays_unverified():
    """Where the source does not establish the code, the difference is preserved.

    Cebu appears once with each of two codes, so neither is the port's code.
    """
    assert "cebu, philippines" not in port_policy.CORPUS_PORT_CODES
    assert port_policy.code_state("CEBU, PHILIPPINES (PHCEB)") == port_policy.UNESTABLISHED
    assert not port_policy.equal("CEBU, PHILIPPINES (PHCEB)", "CEBU, PHILIPPINES")


def test_r10_terminal_qualifiers_are_still_never_stripped():
    assert not port_policy.equal("PORT KLANG (WESTPORT), MALAYSIA",
                                 "PORT KLANG (NORTHPORT), MALAYSIA")
    assert not port_policy.equal("PORT KLANG (WESTPORT), MALAYSIA (MYPKG)",
                                 "PORT KLANG (NORTHPORT), MALAYSIA (MYPKG)")


def test_r10_alternatives_are_still_not_collapsed():
    assert not port_policy.equal("NANTONG, CHINA (CNNTG)",
                                 "RUGAO/NANTONG/SHANGHAI, CHINA (CNSHA)")


def test_r10_the_table_is_derived_from_repeated_source_evidence():
    """Every entry clears the documented threshold; it is not hand-tuned."""
    from pathlib import Path
    import sys

    sys.path.insert(0, "scripts")
    from derive_port_codes import MIN_OBSERVATIONS, derive, observations

    root = Path("resources/sdoc-hackathon-bundle")
    counts = observations(root)
    derived, rejected = derive(counts, MIN_OBSERVATIONS)

    assert derived == port_policy.CORPUS_PORT_CODES, (
        "the shipped table does not match what the source evidence derives"
    )
    # Ports without dominant evidence are excluded on purpose.
    for entry in rejected:
        assert entry["port"] not in port_policy.CORPUS_PORT_CODES


def test_r10_an_unknown_port_cannot_have_a_validated_code():
    """A port the source has never recorded gets no free pass."""
    assert port_policy.code_state("ATLANTIS, ELSEWHERE (XXATL)") == port_policy.UNESTABLISHED
    assert not port_policy.equal("ATLANTIS, ELSEWHERE", "ATLANTIS, ELSEWHERE (XXATL)")
