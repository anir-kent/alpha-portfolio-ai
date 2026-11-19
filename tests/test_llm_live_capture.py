"""Seam: the HTTP API, with the pipeline's LLM Graph running live on the chat model `get_chat_model` builds, and the
provider stood in by a handler under `httpx` (ADR-0011). It checks what reaches the wire (one request per call: SDK
retries are off; the structured-output shape; OpenRouter's attribution and routing parameters) and that every call is
one Exchange holding what LangChain sent and received. No network."""

import json

import httpx
import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.chat_model import get_chat_model
from app.db import AuditEventRow
from tests.chat_completions import completion
from tests.conftest import SEED_PASSWORD
from tests.fake_chat import serve_chat
from tests.test_ai_recommendations import ai  # noqa: F401  (fixture)
from tests.test_llm_exchanges import extraction_event, upload
from tests.test_queue import seeded  # noqa: F401  (fixture)

API_KEY = "sk-live-secret-do-not-store"


@pytest.fixture
def live_app(app, settings, monkeypatch):
    """Returns a builder: the test app with its pipeline on the live chat model for `base_url`, over a provider that
    answers with `handler`, plus the request/response pairs the provider saw."""

    def build(handler, *, base_url="https://openrouter.ai/api/v1/", temperature=None):
        wire: list[tuple[httpx.Request, httpx.Response]] = []

        def provider_on(module):
            """The provider under `module`'s network transport: OpenRouter's SDK sends through `httpx`, OpenAI's
            through `httpx2`. The handler sees and answers in `httpx` terms."""

            def send(transport, request):
                as_httpx = httpx.Request(
                    request.method, str(request.url), headers=dict(request.headers), content=request.read()
                )
                response = handler(as_httpx)
                response.read()
                wire.append((as_httpx, response))
                if module is httpx:
                    return response
                return module.Response(response.status_code, headers=dict(response.headers), content=response.content)

            return send

        for module in (httpx, httpx2):
            monkeypatch.setattr(module.HTTPTransport, "handle_request", provider_on(module))
        live = settings.model_copy(
            update={
                "llm_api_key": API_KEY,
                "llm_base_url": base_url,
                "llm_model": "anthropic/claude-sonnet-5.5",
                "llm_temperature": temperature,
            }
        )
        serve_chat(app, get_chat_model(live))
        app.state.llm._secret = API_KEY
        return app, wire

    return build


def task_of(request: httpx.Request) -> str:
    return json.loads(request.content)["response_format"]["json_schema"]["name"]


def as_role(app, role) -> TestClient:
    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": role, "password": SEED_PASSWORD}).status_code == 200
    return c


def extraction_exchange(app, report) -> dict:
    ref = extraction_event(app, report["id"])["exchanges"]
    assert len(ref) == 1
    r = as_role(app, "auditor").get(f"/api/llm/exchanges/{ref[0]['exchange_id']}")
    assert r.status_code == 200, r.text
    return r.json()


@pytest.mark.parametrize("base_url", ["https://openrouter.ai/api/v1/", "https://gw.example/v1"])
def test_a_live_call_is_one_request_and_one_exchange_holding_what_was_sent_and_received(live_app, base_url):
    app, wire = live_app(lambda r: completion(), base_url=base_url)
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] == "complete", report
    ex = extraction_exchange(app, report)

    assert len(wire) == 1
    request, _ = wire[0]
    assert ex["messages"] == json.loads(request.content)["messages"]  # LangChain's messages are the wire's
    assert len(ex["messages"]) == 2
    assert ex["messages"][0]["content"].startswith(ex["system_text"] + "\n\nJSON schema of the reply:\n")
    assert ex["messages"][1] == {"role": "user", "content": ex["user_prompt"]}
    assert ex["raw_reply"] == '{"insights": []}' and ex["parsed_content"] == {"insights": []}
    assert (ex["usage"]["input_tokens"], ex["usage"]["output_tokens"], ex["usage"]["total_tokens"]) == (321, 45, 366)
    assert (ex["mode"], ex["outcome"], ex["graph_node"]) == ("live", "ok", "generate")
    assert ex["endpoint_host"] == request.url.host
    assert ex["model"] == "anthropic/claude-sonnet-5.5"
    assert isinstance(ex["latency_ms"], int) and ex["latency_ms"] >= 0


@pytest.mark.parametrize("base_url", ["https://openrouter.ai/api/v1/", "https://gw.example/v1"])
def test_structured_output_goes_out_as_one_native_json_schema_request_named_after_the_task(live_app, base_url):
    app, wire = live_app(lambda r: completion(), base_url=base_url)
    upload(as_role(app, "research_analyst"))
    ((request, _),) = wire
    body = json.loads(request.content)
    assert body["response_format"]["type"] == "json_schema"
    assert body["response_format"]["json_schema"]["name"] == "insight_extraction"
    assert body["response_format"]["json_schema"]["schema"]["properties"]["insights"]
    assert "tools" not in body and "tool_choice" not in body  # not function calling


def test_through_openrouter_a_call_carries_the_attribution_title_and_requires_every_parameter(live_app):
    sent = {}
    for base_url in ("https://openrouter.ai/api/v1/", "https://gw.example/v1"):
        app, wire = live_app(lambda r: completion(), base_url=base_url)
        upload(as_role(app, "research_analyst"))
        assert len(wire) == 1
        sent[base_url] = wire[0][0]
    openrouter, other = sent.values()
    assert str(openrouter.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert openrouter.headers["x-title"] == "Portfolio Rebalancing"
    assert json.loads(openrouter.content)["provider"] == {"require_parameters": True}
    assert str(other.url) == "https://gw.example/v1/chat/completions"
    assert "provider" not in json.loads(other.content) and "x-title" not in other.headers  # the plain protocol


def test_temperature_is_sent_only_when_configured(live_app):
    bodies = []
    for temperature in (None, 0.0):
        app, wire = live_app(lambda r: completion(), temperature=temperature)
        upload(as_role(app, "research_analyst"))
        bodies.append(json.loads(wire[0][0].content))
    unset, zero = bodies
    assert "temperature" not in unset and zero["temperature"] == 0.0


def stored_text(app) -> str:
    with app.state.session_factory() as db:
        rows = " ".join(str(v) for row in db.execute(text("SELECT * FROM llm_exchanges")) for v in row)
        return rows + " ".join(r.payload_json for r in db.scalars(select(AuditEventRow)))


@pytest.mark.parametrize("base_url", ["https://openrouter.ai/api/v1/", "https://gw.example/v1"])
@pytest.mark.parametrize("status", [503, 500, 429])
def test_a_failing_http_response_is_one_request_and_one_error_exchange(live_app, base_url, status):
    """Retries off: a status an SDK would retry by default still reaches the provider once."""
    app, wire = live_app(lambda r: httpx.Response(status, text="upstream overloaded"), base_url=base_url)
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] == "failed"
    assert len(wire) == 1  # nothing reached the provider that capture did not see
    ex = extraction_exchange(app, report)
    assert (ex["outcome"], ex["mode"], ex["graph_node"]) == ("error", "live", "generate")
    assert "LLM call failed" in ex["error"]
    assert ex["messages"] == json.loads(wire[0][0].content)["messages"]  # the request that was sent is on record
    assert ex["parsed_content"] is None
    with app.state.session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM llm_exchanges")).scalar() == 1


def test_a_connection_failure_is_one_attempt_and_one_error_exchange(live_app):
    def reset(request):
        raise httpx.ConnectError("connection reset", request=request)

    attempts = []

    def count_and_reset(request):
        attempts.append(request)
        reset(request)

    app, _ = live_app(count_and_reset)
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] == "failed" and len(attempts) == 1
    assert extraction_exchange(app, report)["outcome"] == "error"


@pytest.mark.parametrize("base_url", ["https://openrouter.ai/api/v1/", "https://gw.example/v1"])
def test_the_api_key_never_appears_in_any_exchange_even_when_the_provider_echoes_it(live_app, base_url):
    app, wire = live_app(
        lambda r: httpx.Response(401, text=f"bad credential {r.headers['authorization']}"), base_url=base_url
    )
    report = upload(as_role(app, "research_analyst")).json()
    assert wire[0][0].headers["authorization"] == f"Bearer {API_KEY}"  # it really was sent
    ex = extraction_exchange(app, report)
    assert ex["outcome"] == "error"
    for blob in (json.dumps(ex), stored_text(app), json.dumps(report)):
        assert API_KEY not in blob and "authorization" not in blob.lower()


def test_a_reply_that_is_not_json_is_an_ok_exchange_that_keeps_the_raw_reply_and_fails_the_step(live_app):
    prose = "Sure! Here are the insights you asked for, in prose."
    app, _ = live_app(lambda r: completion(prose))
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] == "failed"
    ex = extraction_exchange(app, report)
    assert (ex["outcome"], ex["raw_reply"], ex["parsed_content"]) == ("ok", prose, None)
    assert ex["usage"]["total_tokens"] == 366


# --- inside an Analysis Run: Exchanges go through the run's own session, before each step's Audit Event -----------

STEP_REPLIES = {  # task -> what the provider answers; replies a step rejects are still `ok` Exchanges
    "research_tilt": '{"tilts": []}',
    "recommendation_narrative": '{"claims": []}',
    "priority_narrative": '{"claims": []}',
}
STEP_EVENTS = {"research_tilt_proposed", "memo_generated", "priority_narrative_generated"}


def step_events(app) -> list[dict]:
    with app.state.session_factory() as db:
        rows = db.scalars(select(AuditEventRow).where(AuditEventRow.type.in_(STEP_EVENTS))).all()
        return [json.loads(r.payload_json) for r in rows]


def test_inside_an_analysis_run_every_live_request_is_an_exchange_its_step_event_anchors(live_app, ai):
    ai.approve("Information Technology", "equity")
    app, wire = live_app(lambda r: completion(STEP_REPLIES[task_of(r)]))
    ai.run()
    events = step_events(app)
    assert events and len(events) == len(wire)  # one Exchange per request, each anchored by its step's event
    auditor = as_role(app, "auditor")
    unmatched = list(wire)
    for payload in events:
        (ref,) = payload["exchanges"]  # a Trajectory of one
        ex = auditor.get(f"/api/llm/exchanges/{ref['exchange_id']}").json()
        assert (ex["hash"], ex["outcome"], ex["mode"], ex["graph_node"]) == (
            ref["exchange_hash"],
            "ok",
            "live",
            "generate",
        )
        request, response = next(p for p in unmatched if json.loads(p[0].content)["messages"] == ex["messages"])
        unmatched.remove((request, response))
        assert ex["task"] == task_of(request) and ex["raw_reply"] == STEP_REPLIES[ex["task"]]
    assert not unmatched
    assert auditor.get("/api/audit/verify").json()["valid"]
