"""C3 regression: the run configuration identity must move when behaviour moves.

On 675f0d3 ``config_identity()`` was byte-identical to 58f2a7e's despite changed
grounding, extraction and port semantics: ``CODE_RELEASE`` was stale and
``POLICY_VERSIONS`` duplicated a version the ports module had already moved past
(the manifest said ``ports-1.0.0`` while the module declared ``2.0.0``). The
identity check therefore could not detect a code or policy upgrade.
"""

from backend.intelligence.config import load_config, policy_tables, policy_versions
from backend.intelligence.policies import ports as port_policy

def test_c3_policy_versions_come_from_their_own_modules():
    """A duplicated constant drifted; versions are now read where they are defined."""
    versions = policy_versions()
    assert versions["ports"] == port_policy.VERSION
    from backend.intelligence import comparison, grounding, normalization

    assert versions["grounding"] == grounding.VERSION
    assert versions["normalization"] == normalization.VERSION
    assert versions["comparison"] == comparison.VERSION


def test_c3_changing_a_policy_version_changes_the_identity(monkeypatch):
    config = load_config()
    before = config.config_identity()
    monkeypatch.setattr(port_policy, "VERSION", "ports-99.0.0")
    assert config.config_identity() != before


def test_c3_changing_the_port_table_changes_the_identity(monkeypatch):
    config = load_config()
    before = config.config_identity()
    monkeypatch.setitem(port_policy.CORPUS_PORT_CODES, "atlantis, elsewhere", "XXATL")
    assert config.config_identity() != before


def test_c3_changing_the_table_approval_changes_the_identity(monkeypatch):
    config = load_config()
    before = config.config_identity()
    monkeypatch.setattr(port_policy, "PORT_TABLE_APPROVED", not port_policy.PORT_TABLE_APPROVED)
    assert config.config_identity() != before


def test_c3_changing_an_alias_table_changes_the_identity(monkeypatch):
    from backend.intelligence.policies import aliases

    config = load_config()
    before = config.config_identity()
    monkeypatch.setitem(aliases.FIELD_ALIASES, "shipper",
                        aliases.FIELD_ALIASES["shipper"] + ("consignor",))
    assert config.config_identity() != before


def test_c3_changing_the_release_changes_the_identity(monkeypatch):
    from backend.intelligence import config as config_module

    config = load_config()
    before = config.config_identity()
    monkeypatch.setattr(config_module, "CODE_RELEASE", "person-a-99.0.0")
    assert config.config_identity() != before


def test_c3_the_identity_is_stable_for_the_same_implementation():
    """Same pinned code and configuration, same identity across reloads."""
    first = load_config().config_identity()
    second = load_config().config_identity()
    assert first == second


def test_c3_the_identity_differs_from_the_reviewed_commits():
    """675f0d3 shared 58f2a7e's identity despite changed semantics."""
    assert load_config().config_identity() != "person-a-v1+cdfa29acf2c2f216"


def test_c3_the_manifest_records_the_tables_behaviour_depends_on():
    tables = policy_tables()
    for key in ("port_codes", "port_table_approved", "country_alpha2",
                "field_aliases", "negative_labels", "unit_factors"):
        assert key in tables, key


