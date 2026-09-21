"""Participant bundle handling.

The previous version ingested email_009 through the public route and streamed
its document as demo-safe. Real correspondence is not demo-safe, so participant
ingestion is exercised directly here and the public stream is asserted refused.
Separate demo-content tests use the independently authored fixtures.
"""

import pytest

from backend import crud, schemas
from backend.intelligence.config import load_config
from backend.intelligence.ingestion import build_registries, ingest_case, read_source_bytes
from backend.intelligence.types import SourceDataIssue
from tests.conftest import DEMO_MATCH
from tests.helpers import create_and_wait


@pytest.fixture(scope="module")
def participant():
    config = load_config()
    return config, build_registries(config)


def test_participant_records_map_honestly(participant):
    """Real metadata, real hashes, real roles deferred to content."""
    config, registries = participant
    snapshot = ingest_case("email_009", namespace="EVAL", case_id="email_009",
                           registries=registries, config=config)

    assert snapshot.from_address == "arlene_yamomo@aprilasia.com"
    assert len(snapshot.sources) == 2
    assert snapshot.received_at is None          # the bundle supplies no receipt time
    assert snapshot.registry_kind == "participant"
    assert snapshot.demo_safe is False

    for source in snapshot.sources:
        assert source.present is True
        assert source.content_hash and source.content_hash != "mock_hash"
        assert source.size_bytes and source.size_bytes > 0
        assert source.demo_safe is False


def test_participant_bytes_are_retrievable_only_through_verified_identity(participant):
    config, registries = participant
    snapshot = ingest_case("email_009", namespace="EVAL", case_id="email_009",
                           registries=registries, config=config)
    document_id = snapshot.sources[0].document_id

    data = read_source_bytes(snapshot, document_id, registries=registries)
    assert b"SHIPPING INSTRUCTION" in data or b"BILL OF LADING" in data

    with pytest.raises(SourceDataIssue):
        read_source_bytes(snapshot, "doc_not_in_this_snapshot", registries=registries)


def test_participant_documents_are_not_streamed_to_a_public_caller(client):
    """A DEMO caller cannot pull real correspondence out of the document endpoint."""
    response = client.post("/api/v1/cases", json={"email_id": "email_004"})
    assert response.status_code in (200, 202)
    created = response.json()

    assert created["run"]["demo_safe"] is False
    for document in created["documents"]:
        assert document["demo_safe"] is False
        stream = client.get(f"/api/v1/documents/{document['document_id']}/content")
        assert stream.status_code == 404, "participant bytes must not be public"


def test_demo_fixture_documents_are_streamable(client):
    """Independently authored demo content is what a public caller may read."""
    case = create_and_wait(client, DEMO_MATCH, "COMPLETED")
    assert case["run"]["demo_safe"] is True
    for document in case["documents"]:
        assert document["demo_safe"] is True
        stream = client.get(f"/api/v1/documents/{document['document_id']}/content")
        assert stream.status_code == 200
        assert stream.content


def test_the_same_email_id_in_demo_and_eval_gets_separate_document_identities(participant):
    """I-16: DEMO and EVAL never share a document identity."""
    config, registries = participant
    demo = ingest_case("email_004", namespace="DEMO", case_id="email_004",
                       registries=registries, config=config)
    evaluation = ingest_case("email_004", namespace="EVAL", case_id="email_004",
                             registries=registries, config=config)
    demo_ids = {s.document_id for s in demo.sources}
    eval_ids = {s.document_id for s in evaluation.sources}
    assert demo_ids.isdisjoint(eval_ids)


def test_the_bundle_inventory_is_recomputed_not_assumed(participant):
    """520 is an observation about this revision, never a constant in the code."""
    _config, registries = participant
    ids = registries["participant"].email_ids()
    assert len(ids) > 0
    assert all(name.startswith("email_") for name in ids)


def test_public_participant_ingestion_can_be_switched_off(monkeypatch, client):
    """With the gate closed, a public caller can only ingest demo fixtures."""
    from backend import crud

    monkeypatch.setenv("INTELLIGENCE_ALLOW_PUBLIC_PARTICIPANT_INGEST", "false")
    crud.reset_intelligence_cache()
    try:
        refused = client.post("/api/v1/cases", json={"email_id": "email_004"})
        assert refused.status_code == 404

        allowed = client.post("/api/v1/cases", json={"email_id": DEMO_MATCH})
        assert allowed.status_code in (200, 202)

        # The authenticated operator path is unaffected.
        operator = client.post("/api/v1/cases", json={"email_id": "email_009"},
                               headers={"X-Run-Kind": "EVAL"})
        assert operator.status_code == 202
    finally:
        monkeypatch.delenv("INTELLIGENCE_ALLOW_PUBLIC_PARTICIPANT_INGEST", raising=False)
        crud.reset_intelligence_cache()
