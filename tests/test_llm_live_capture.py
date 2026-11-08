"""Seam: the HTTP API, with the step-facing LLM call running on pydantic-ai over a live Model whose provider is an
`httpx.MockTransport`. Every model request is an LLM Exchange holding the bytes that crossed the wire (ADR-0004 as
amended by ADR-0010). No network."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.db import AuditEventRow
from app.exchanges import ModelLlm, endpoint_host
from app.pydantic_llm import build_live_model
from tests.conftest import SEED_PASSWORD
from tests.test_ai_recommendations import ai  # noqa: F401  (fixture)
from tests.test_assistant import unwritable_store
from tests.test_llm_exchanges import extraction_event, upload
from tests.test_queue import seeded  # noqa: F401  (fixture)

API_KEY = "sk-live-secret-do-not-store"
REPLY_TEXT = '{"insights": []}'


def completion(content=REPLY_TEXT, **extra) -> httpx.Response:
    """A chat-completions reply as OpenRouter sends it (pydantic-ai's OpenRouter model requires `provider`)."""
    return httpx.Response(
        200,
        json={
            "id": "gen-1",
            "object": "chat.completion",
            "created": 1,
            "model": "anthropic/claude-sonnet-5.5",
            "provider": "Anthropic",
            "usage": {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366},
            "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": content}}],
            **extra,
        },
    )


@pytest.fixture
def live_app(app, settings):
    """Returns a builder: the test app with its LLM swapped for the pydantic-ai adapter over a live Model whose
    provider is `handler`, plus the request/response pairs the provider saw."""

    def build(handler, *, base_url="https://gw.example/v1", temperature=None):
        wire: list[tuple[httpx.Request, httpx.Response]] = []

        def provider(request: httpx.Request) -> httpx.Response:
            response = handler(request)
            wire.append((request, response))
            return response

        live = settings.model_copy(
            update={
                "llm_mode": "live",
                "llm_api_key": API_KEY,
                "llm_base_url": base_url,
                "llm_model": "anthropic/claude-sonnet-5.5",
                "llm_temperature": temperature,
            }
        )
        app.state.llm = ModelLlm(
            build_live_model(live, httpx.MockTransport(provider)),
            app.state.session_factory,
            mode="live",
            endpoint_host=endpoint_host(live),
        )
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


def test_a_live_exchange_stores_the_request_messages_and_raw_reply_exactly_as_they_crossed_the_wire(live_app):
    app, wire = live_app(lambda r: completion())
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] != "failed"
    ex = extraction_exchange(app, report)

    assert len(wire) == 1
    request, response = wire[0]
    assert ex["messages"] == json.loads(request.content)["messages"]
    assert ex["raw_reply"] == response.content.decode()
    assert len(ex["messages"]) == 2  # no framework-authored preamble: the prompt goes out as the step wrote it
    assert ex["messages"][0]["role"] == "system"
    assert ex["messages"][0]["content"].startswith(ex["system_text"] + "\n\nJSON schema of the reply:\n")
    assert ex["messages"][1] == {"role": "user", "content": ex["user_prompt"]}
    assert (ex["mode"], ex["outcome"], ex["endpoint_host"]) == ("live", "ok", "gw.example")
    assert ex["parsed_content"] == {"insights": []}
    assert ex["usage"] == {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366}
    assert ex["model"] == "anthropic/claude-sonnet-5.5"
    assert isinstance(ex["latency_ms"], int) and ex["latency_ms"] >= 0


def test_through_openrouter_a_call_carries_the_attribution_title_and_requires_every_parameter(live_app):
    sent = {}
    for base_url in ("https://openrouter.ai/api/v1/", "https://gw.example/v1"):
        app, wire = live_app(lambda r: completion(), base_url=base_url)
        upload(as_role(app, "research_analyst"))
        assert len(wire) == 1
        sent[base_url] = wire[0][0]
    openrouter, other = (sent[u] for u in sent)
    assert str(openrouter.url) == "https://openrouter.ai/api/v1/chat/completions"
    assert openrouter.headers["x-title"] == "Portfolio Rebalancing"
    assert json.loads(openrouter.content)["provider"] == {"require_parameters": True}
    assert json.loads(openrouter.content)["response_format"]["type"] == "json_schema"
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
def test_a_failing_http_response_is_one_request_and_one_error_exchange(live_app, base_url):
    app, wire = live_app(lambda r: httpx.Response(503, text="upstream overloaded"), base_url=base_url)
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] == "failed"
    assert len(wire) == 1  # SDK retries are off: nothing reaches the provider that capture did not see
    ex = extraction_exchange(app, report)
    assert (ex["outcome"], ex["mode"]) == ("error", "live")
    assert "HTTP 503" in ex["error"] and "upstream overloaded" in ex["error"]
    assert ex["messages"] == json.loads(wire[0][0].content)["messages"]  # the request that was sent is on record
    assert ex["raw_reply"] == "upstream overloaded" and ex["parsed_content"] is None
    with app.state.session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM llm_exchanges")).scalar() == 1


def test_the_api_key_never_appears_in_any_exchange_even_when_the_provider_echoes_it(live_app):
    app, wire = live_app(lambda r: httpx.Response(401, text=f"bad credential {r.headers['authorization']}"))
    report = upload(as_role(app, "research_analyst")).json()
    assert wire[0][0].headers["authorization"] == f"Bearer {API_KEY}"  # it really was sent
    ex = extraction_exchange(app, report)
    assert ex["outcome"] == "error" and "[redacted]" in ex["raw_reply"]
    for blob in (json.dumps(ex), stored_text(app), json.dumps(report)):
        assert API_KEY not in blob and "authorization" not in blob.lower()

    ok_app, _ = live_app(lambda r: completion())
    ok = extraction_exchange(ok_app, upload(as_role(ok_app, "research_analyst")).json())
    assert ok["outcome"] == "ok" and API_KEY not in stored_text(ok_app)


def test_a_reply_that_is_not_json_is_an_error_exchange_that_keeps_the_raw_reply(live_app):
    prose = "Sure! Here are the insights you asked for, in prose."
    app, wire = live_app(lambda r: completion(prose))
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] == "failed"
    ex = extraction_exchange(app, report)
    assert ex["outcome"] == "error" and "not valid JSON" in ex["error"]
    assert ex["raw_reply"] == wire[0][1].content.decode() and prose in ex["raw_reply"]
    assert ex["usage"] == {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366}
    assert ex["parsed_content"] is None


def test_a_reply_the_framework_cannot_read_is_an_error_exchange_that_keeps_the_raw_reply(live_app):
    """OpenRouter's reply shape names the routed provider; one without it is not a completion pydantic-ai accepts."""
    garbled = '{"choices": "nope"}'
    app, wire = live_app(lambda r: httpx.Response(200, text=garbled), base_url="https://openrouter.ai/api/v1/")
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] == "failed" and len(wire) == 1
    ex = extraction_exchange(app, report)
    assert ex["outcome"] == "error" and ex["raw_reply"] == garbled and ex["parsed_content"] is None


def test_a_reply_the_step_rejects_is_still_an_ok_exchange(live_app):
    """Outcome is transport-level: the JSON arrived and parsed, so the Exchange is `ok` even though the step's own
    model refuses it."""
    app, _ = live_app(lambda r: completion('{"insights": "not a list"}'))
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] == "failed"
    ex = extraction_exchange(app, report)
    assert ex["outcome"] == "ok" and ex["parsed_content"] == {"insights": "not a list"}


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
        (ref,) = payload["exchanges"]
        ex = auditor.get(f"/api/llm/exchanges/{ref['exchange_id']}").json()
        assert (ex["hash"], ex["outcome"], ex["mode"]) == (ref["exchange_hash"], "ok", "live")
        request, response = next(p for p in unmatched if json.loads(p[0].content)["messages"] == ex["messages"])
        unmatched.remove((request, response))
        assert ex["task"] == task_of(request) and ex["raw_reply"] == response.content.decode()
    assert not unmatched
    assert auditor.get("/api/audit/verify").json()["valid"]


def test_an_exchange_that_cannot_be_stored_fails_the_call_closed(live_app):
    app, wire = live_app(lambda r: completion())
    app.state.llm = ModelLlm(app.state.llm.model, unwritable_store, mode="live", endpoint_host="gw.example")
    report = upload(as_role(app, "research_analyst")).json()
    assert len(wire) == 1  # the provider answered; capture failed afterwards
    assert report["extraction_status"] == "failed" and report["insights"] == []
    assert "exchanges" not in extraction_event(app, report["id"])  # nothing was stored, so nothing to point at
    assert as_role(app, "auditor").get("/api/audit/verify").json()["valid"]


def test_live_requests_through_a_trajectory_view_share_one_trajectory_in_call_order(live_app):
    from app.llm import LlmRequest

    app, wire = live_app(lambda r: completion('{"answer": "ok"}'))
    turn = app.state.llm.trajectory()
    request = LlmRequest("assistant_answer", "assistant_answer@v1", "system", "user", {"type": "object"})
    first, second = turn.complete(request), turn.complete(request)
    auditor = as_role(app, "auditor")
    exchanges = [auditor.get(f"/api/llm/exchanges/{r.exchange_id}").json() for r in (first, second)]
    assert len(wire) == 2
    assert exchanges[0]["trajectory_id"] == exchanges[1]["trajectory_id"] is not None
    assert [e["trajectory_position"] for e in exchanges] == [0, 1]
    alone = app.state.llm.complete(request)  # a plain call is a Trajectory of one
    assert auditor.get(f"/api/llm/exchanges/{alone.exchange_id}").json()["trajectory_position"] == 0
