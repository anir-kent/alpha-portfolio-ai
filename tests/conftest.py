import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.fake_chat import DemoPipeline
from tests.fake_index import fake_embeddings, fake_reranker, word_tokenizer
from tests.fixtures.demo import SEED_PASSWORD, demo_settings

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


_NETWORK = (httpx, httpx2)
_REAL_TRANSPORTS = {
    module: (module.HTTPTransport.handle_request, module.AsyncHTTPTransport.handle_async_request) for module in _NETWORK
}


@pytest.fixture
def allow_network(monkeypatch):
    """Opts one test (a live smoke test) back into the real network."""
    for module, (sync, async_) in _REAL_TRANSPORTS.items():
        monkeypatch.setattr(module.HTTPTransport, "handle_request", sync)
        monkeypatch.setattr(module.AsyncHTTPTransport, "handle_async_request", async_)


@pytest.fixture(autouse=True, scope="session")
def no_network():
    """No test reaches a real provider: the provider SDKs send through the network transports
    of `httpx` (OpenRouter) and `httpx2` (OpenAI), which refuse here. A live-path test stands a handler in for the
    provider by patching the same methods (tests.test_llm_live_capture)."""

    def refuse(self, request):
        raise ConnectionError(f"no network in tests: {request.url}")

    async def refuse_async(self, request):
        refuse(self, request)

    with pytest.MonkeyPatch.context() as patch:
        for module in _NETWORK:
            patch.setattr(module.HTTPTransport, "handle_request", refuse)
            patch.setattr(module.AsyncHTTPTransport, "handle_async_request", refuse_async)
        yield


@pytest.fixture(autouse=True)
def pipeline_chat_model(monkeypatch):
    """Every app the tests build runs its LLM Graphs on `DemoPipeline`, a fake chat model (ADR-0011), unless a test serves
    its own (`tests.fake_chat.serve_chat`)."""
    monkeypatch.setattr("app.exchanges.get_chat_model", lambda settings: DemoPipeline())


@pytest.fixture(autouse=True)
def offline_index(monkeypatch):
    """The Report Index runs on fake embeddings and a word-count tokenizer: no provider call, no model download."""
    monkeypatch.setattr("app.report_index.get_embeddings", fake_embeddings)
    monkeypatch.setattr("app.report_index.chunk_tokenizer", word_tokenizer)
    monkeypatch.setattr("app.report_index.get_reranker", fake_reranker)


@pytest.fixture
def settings(tmp_path):
    return demo_settings(tmp_path)  # ignores the developer's .env, so local runs see what CI sees


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
