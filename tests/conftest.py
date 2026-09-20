"""Shared test setup.

Every test runs against an isolated database and the synthetic demo registry.
Participant sources are never ingested through a public route here; the tests
that exercise the real bundle do so directly, in their own scope.
"""

import os
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
TEST_DB_PATH = Path(__file__).resolve().parent / "test_shipping.db"

# Set before importing the app: the modules read configuration at import time.
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"
os.environ.setdefault("INTELLIGENCE_DEMO_SOURCE_ROOT", str(REPO_ROOT / "resources" / "demo-fixtures"))
os.environ.setdefault("INTELLIGENCE_SOURCE_ROOT", str(REPO_ROOT / "resources" / "sdoc-hackathon-bundle"))

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from backend.database import Base, SessionLocal, engine  # noqa: E402
from backend.main import app  # noqa: E402

# Demo fixture ids, so no test depends on an unregistered identifier.
DEMO_MATCH = "email_demo_match"
DEMO_MISMATCH = "email_demo_mismatch"
DEMO_MISSING_WEIGHT = "email_demo_missing_weight"
DEMO_NO_ATTACHMENTS = "email_demo_no_attachments"
DEMO_WRONG_DOC = "email_demo_wrong_doc"
DEMO_INVOICE = "email_demo_invoice"
DEMO_DOCUMENT_CHOICE = "email_demo_document_choice"
DEMO_REFERENCE = "email_demo_reference"
DEMO_PDF = "email_demo_pdf"
DEMO_SCANNED = "email_demo_scanned"
DEMO_CORRUPT = "email_demo_corrupt"
DEMO_OFFICE = "email_demo_office"
DEMO_NEEDS_MODEL = "email_demo_needs_model"


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(autouse=True)
def isolate_database():
    """Empty every table before each test, so results never depend on test order."""
    db = SessionLocal()
    try:
        for table in ("accepted_decisions", "jobs", "cases"):
            db.execute(text(f"DELETE FROM {table}"))
        db.commit()
    finally:
        db.close()
    yield


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
