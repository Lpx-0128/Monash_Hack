import os
import pytest
from pathlib import Path

# Ensure tests use an isolated test database
TEST_DB_PATH = Path(__file__).resolve().parent / "test_shipping.db"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

from fastapi.testclient import TestClient
from backend.main import app
from backend.database import init_db, engine, Base


@pytest.fixture(scope="session", autouse=True)
def setup_test_db():
    if TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink()
        except Exception:
            pass
    init_db()
    yield
    if TEST_DB_PATH.exists():
        try:
            TEST_DB_PATH.unlink()
        except Exception:
            pass


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c
