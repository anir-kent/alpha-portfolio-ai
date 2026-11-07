import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fixtures.suggested_questions import SEED_PASSWORD, replay_settings

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
    return replay_settings(tmp_path)  # ignores the developer's .env, so local runs see what CI sees


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
