from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

SEED_PASSWORD = "test-only-password"

ROLES = [
    "relationship_manager",
    "advisor",
    "portfolio_manager",
    "research_analyst",
    "compliance_officer",
    "investment_committee",
    "auditor",
    "platform_owner",
]


@pytest.fixture
def settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        seed_user_password=SEED_PASSWORD,
        market_data_snapshot_path=str(tmp_path / "snapshot.json"),
        llm_mode="recorded",
        llm_recordings_dir=str(Path(__file__).parent / "fixtures" / "llm"),
    )


@pytest.fixture
def app(settings):
    return create_app(settings)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(app):
    """Returns a function that yields a fresh client logged in as a role."""

    def _login(role: str) -> TestClient:
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"username": role, "password": SEED_PASSWORD})
        assert r.status_code == 200, r.text
        return c

    return _login
