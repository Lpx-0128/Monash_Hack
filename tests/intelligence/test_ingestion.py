"""Source mapping, identity and containment (handoff cases A-01 to A-04)."""

import json

import pytest

from backend.intelligence.ingestion import (
    MISSING_FILE,
    SourceRegistry,
    compute_input_version,
    document_id_for,
    ingest_case,
)
from backend.intelligence.types import SourceDataIssue

from .conftest import PARTICIPANT_ROOT


def test_a01_mapping_keeps_body_private_and_receipt_time_null(registries, config):
    """A-01: the body is preserved for classification and received_at stays null."""
    snapshot = ingest_case("email_demo_match", namespace="DEMO", case_id="email_demo_match",
                           registries=registries, config=config)
    assert "compare the SI and draft BL" in snapshot.body
    # The bundle supplies no receipt timestamp, so the value is explicitly null.
    assert snapshot.received_at is None
    assert snapshot.email_id == "email_demo_match"
    assert len(snapshot.sources) == 2


def test_a02_valid_timestamp_kept_and_malformed_rejected(tmp_path, config):
    """A-02: a real timestamp normalizes; a malformed non-null one is rejected."""
    root = tmp_path / "registry"
    (root / "inbox").mkdir(parents=True)
    (root / "attachments").mkdir()

    def write(email_id, received_at):
        (root / "inbox" / f"{email_id}.json").write_text(json.dumps({
            "email_id": email_id, "from": "a@b.invalid", "subject": "s",
            "body": "b", "attachments": [], "received_at": received_at,
        }))

    write("email_good", "2026-03-04T05:06:07Z")
    write("email_bad", "last Tuesday")
    registries = {"participant": SourceRegistry("participant", root, demo_safe=False)}

    good = ingest_case("email_good", namespace="DEMO", case_id="email_good",
                       registries=registries, config=config)
    assert good.received_at == "2026-03-04T05:06:07Z"

    with pytest.raises(SourceDataIssue, match="received_at"):
        ingest_case("email_bad", namespace="DEMO", case_id="email_bad",
                    registries=registries, config=config)


@pytest.mark.parametrize("reference", [
    "../../etc/passwd",
    "/etc/passwd",
    "attachments/../../secrets.txt",
    "https://example.invalid/payload.pdf",
    "file:///etc/passwd",
])
def test_a03_unsafe_references_are_refused(reference, tmp_path):
    """A-03: traversal, absolute paths and remote URLs never open anything."""
    registry = SourceRegistry("participant", tmp_path, demo_safe=False)
    with pytest.raises(SourceDataIssue):
        registry.resolve(reference)


def test_a03_symlink_escape_is_refused(tmp_path):
    """A-03: a symlink pointing outside the root is refused after resolution."""
    root = tmp_path / "root"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("private")
    (root / "link.txt").symlink_to(secret)

    registry = SourceRegistry("participant", root, demo_safe=False)
    with pytest.raises(SourceDataIssue, match="escapes"):
        registry.resolve("link.txt")


def test_a04_missing_listed_file_is_distinct_from_an_omitted_attachment(tmp_path, config):
    """A-04: a listed-but-absent file and an empty attachment list differ."""
    root = tmp_path / "registry"
    (root / "inbox").mkdir(parents=True)
    (root / "attachments").mkdir()
    (root / "inbox" / "email_gone.json").write_text(json.dumps({
        "email_id": "email_gone", "from": "a@b.invalid", "subject": "s", "body": "b",
        "attachments": ["attachments/never_written_BL.txt"],
    }))
    (root / "inbox" / "email_none.json").write_text(json.dumps({
        "email_id": "email_none", "from": "a@b.invalid", "subject": "s", "body": "b",
        "attachments": [],
    }))
    registries = {"participant": SourceRegistry("participant", root, demo_safe=False)}

    gone = ingest_case("email_gone", namespace="DEMO", case_id="email_gone",
                       registries=registries, config=config)
    assert len(gone.sources) == 1
    missing = gone.sources[0]
    assert missing.present is False
    assert missing.issue == MISSING_FILE
    # A missing file has no invented hash and no fabricated bytes.
    assert missing.content_hash is None
    assert missing.size_bytes is None

    none = ingest_case("email_none", namespace="DEMO", case_id="email_none",
                       registries=registries, config=config)
    assert none.sources == ()
    # The two situations produce different input versions.
    assert gone.input_version != none.input_version


def test_unregistered_email_id_produces_no_source(registries, config):
    """An id nobody registered is refused rather than invented."""
    with pytest.raises(SourceDataIssue, match="not present in any configured source registry"):
        ingest_case("email_made_up", namespace="DEMO", case_id="email_made_up",
                    registries=registries, config=config)


def test_content_hashes_are_real_and_reproducible(registries, config):
    """Hashes are SHA-256 over the actual bytes, not a placeholder."""
    import hashlib

    snapshot = ingest_case("email_demo_match", namespace="DEMO", case_id="email_demo_match",
                           registries=registries, config=config)
    for source in snapshot.sources:
        path = registries["synthetic_demo"].resolve(source.declared_path)
        assert source.content_hash == hashlib.sha256(path.read_bytes()).hexdigest()
        assert source.content_hash != "mock_hash"

    again = ingest_case("email_demo_match", namespace="DEMO", case_id="email_demo_match",
                        registries=registries, config=config)
    assert again.input_version == snapshot.input_version


def test_document_identity_is_opaque_and_namespace_scoped():
    """A filename is not a document id, and DEMO and EVAL never collide."""
    demo = document_id_for("DEMO", "email_004", "participant", "attachments/x_SI.txt", "abc")
    evaluation = document_id_for("EVAL", "email_004", "participant", "attachments/x_SI.txt", "abc")
    assert demo != evaluation
    assert "x_SI.txt" not in demo
    assert demo.startswith("doc_")


def test_participant_sources_are_not_demo_safe(registries, config):
    """Participant correspondence is never marked publicly streamable."""
    snapshot = ingest_case("email_004", namespace="DEMO", case_id="email_004",
                           registries=registries, config=config)
    assert snapshot.registry_kind == "participant"
    assert snapshot.demo_safe is False
    assert all(source.demo_safe is False for source in snapshot.sources)


def test_demo_fixtures_are_demo_safe(registries, config):
    snapshot = ingest_case("email_demo_match", namespace="DEMO", case_id="email_demo_match",
                           registries=registries, config=config)
    assert snapshot.registry_kind == "synthetic_demo"
    assert snapshot.demo_safe is True
    assert all(source.demo_safe is True for source in snapshot.sources)


def test_input_version_changes_with_content():
    """Different attachment hashes produce different input versions."""
    from backend.intelligence.ingestion import SourceRef

    record = {"from": "a@b.invalid", "subject": "s", "body": "b", "received_at": None}

    def ref(content_hash):
        return SourceRef(document_id="d", declared_path="attachments/a.txt", filename="a.txt",
                         media_type="text/plain", content_hash=content_hash, size_bytes=10,
                         present=True, demo_safe=True)

    first = compute_input_version("email_x", record, [ref("aaa")])
    second = compute_input_version("email_x", record, [ref("bbb")])
    assert first != second
