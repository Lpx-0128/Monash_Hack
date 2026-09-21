"""Fixtures for the Person A unit tests."""

import hashlib
from pathlib import Path

import pytest

from backend.intelligence.config import load_config
from backend.intelligence.ingestion import build_registries
from backend.intelligence.parsers.router import parse_source

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
DEMO_ATTACHMENTS = REPO_ROOT / "resources" / "demo-fixtures" / "attachments"
PARTICIPANT_ROOT = REPO_ROOT / "resources" / "sdoc-hackathon-bundle"


@pytest.fixture(scope="session")
def config():
    return load_config()


@pytest.fixture(scope="session")
def registries(config):
    return build_registries(config)


@pytest.fixture(scope="session")
def parse(config):
    """Parse raw bytes exactly as a run would, returning the immutable artifact."""

    def _parse(data: bytes, filename: str = "doc.txt", document_id: str = "doc_test"):
        return parse_source(
            data,
            document_id=document_id,
            content_hash=hashlib.sha256(data).hexdigest(),
            filename=filename,
            media_type="",
            config=config,
        )

    return _parse


@pytest.fixture(scope="session")
def parse_demo(parse):
    """Parse one of the committed synthetic demo attachments."""

    def _parse_demo(name: str, document_id: str = None):
        path = DEMO_ATTACHMENTS / name
        return parse(path.read_bytes(), filename=name, document_id=document_id or name)

    return _parse_demo
