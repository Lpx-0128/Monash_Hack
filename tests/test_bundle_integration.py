import pytest
from backend import schemas


def test_ingest_and_stream_real_bundle_email(client):
    # Ingest email_009 from the organizer bundle
    r = client.post("/api/v1/cases", json={"email_id": "email_009"})
    assert r.status_code in (200, 202)
    case_data = r.json()

    assert case_data["email"]["from"] == "arlene_yamomo@aprilasia.com"
    assert len(case_data["documents"]) == 2

    si_doc = next(d for d in case_data["documents"] if d["role"] == "SI")
    assert si_doc["filename"] == "email_009_SI.txt"

    # Stream the attachment content
    stream_resp = client.get(f"/api/v1/documents/{si_doc['document_id']}/content")
    assert stream_resp.status_code == 200
    content_text = stream_resp.text
    assert "SHIPPING INSTRUCTION" in content_text
    assert stream_resp.headers["content-type"].startswith("text/plain")
