"""Seam: the HTTP API, with the pipeline's `complete` running its LLM Graph on a fake chat model (ADR-0011). Every model
call is one LLM Exchange, written by the capture callback: the messages sent, the raw reply, usage, latency and the
Graph Node that made the call. The step's Audit Event anchors it as a Trajectory of one. No network."""

import json

from sqlalchemy import text

from app.db import LlmExchangeRow
from app.exchanges import exchange_digest
from tests.fake_chat import FakeChatModel, serve_chat
from tests.test_assistant import unwritable_store
from tests.test_llm_exchanges import extraction_event
from tests.uploads import upload

REPLY: dict = {"insights": []}


def extraction_exchange(app, login, report) -> dict:
    ref = extraction_event(app, report["id"])["exchanges"]
    assert len(ref) == 1  # a Trajectory of one
    r = login("auditor").get(f"/api/llm/exchanges/{ref[0]['exchange_id']}")
    assert r.status_code == 200, r.text
    return r.json()


def test_an_exchange_stores_the_messages_raw_reply_usage_latency_and_graph_node(app, login):
    model = serve_chat(app, FakeChatModel(REPLY, model_name="fake-model-1"))
    report = upload(login("research_analyst")).json()
    assert report["extraction_status"] == "complete"
    ex = extraction_exchange(app, login, report)

    assert len(model.requests) == 1  # one model call per `complete`
    assert ex["messages"] == [
        {"role": "system", "content": model.requests[0].system},
        {"role": "user", "content": ex["user_prompt"]},
    ]
    assert ex["messages"][0]["content"].startswith(ex["system_text"] + "\n\nJSON schema of the reply:\n")
    assert ex["raw_reply"] == json.dumps(REPLY) and ex["parsed_content"] == REPLY
    assert ex["usage"] == {"input_tokens": 11, "output_tokens": 7, "total_tokens": 18}
    assert isinstance(ex["latency_ms"], int) and ex["latency_ms"] >= 0
    assert (ex["graph_node"], ex["outcome"], ex["model"]) == ("generate", "ok", "fake-model-1")
    assert (ex["task"], ex["prompt_version"]) == ("insight_extraction", "insight_extraction@v2")


def test_the_model_is_asked_for_native_json_schema_output_named_after_the_task(app, login):
    model = serve_chat(app, FakeChatModel(REPLY))
    upload(login("research_analyst"))
    (request,) = model.requests
    assert request.response_format["type"] == "json_schema"
    assert request.response_format["json_schema"]["name"] == "insight_extraction"
    assert request.response_format["json_schema"]["schema"]["properties"]["insights"]


def test_a_reply_that_is_not_json_is_an_ok_exchange_and_a_failed_step(app, login):
    prose = "Sure! Here are the insights you asked for, in prose."
    serve_chat(app, FakeChatModel(prose))
    report = upload(login("research_analyst")).json()
    assert report["extraction_status"] == "failed" and "not valid JSON" in report["extraction_error"]
    ex = extraction_exchange(app, login, report)
    assert (ex["outcome"], ex["raw_reply"], ex["parsed_content"]) == ("ok", prose, None)


def test_a_reply_that_is_json_but_not_an_object_fails_the_step(app, login):
    serve_chat(app, FakeChatModel("[1, 2]"))
    report = upload(login("research_analyst")).json()
    assert report["extraction_status"] == "failed" and "not a JSON object" in report["extraction_error"]
    assert extraction_exchange(app, login, report)["outcome"] == "ok"


def test_a_reply_the_step_rejects_is_still_an_ok_exchange(app, login):
    serve_chat(app, FakeChatModel({"insights": "not a list"}))
    report = upload(login("research_analyst")).json()
    assert report["extraction_status"] == "failed"
    ex = extraction_exchange(app, login, report)
    assert ex["outcome"] == "ok" and ex["parsed_content"] == {"insights": "not a list"}


def test_a_failing_provider_is_one_error_exchange_that_keeps_the_messages_sent(app, login):
    serve_chat(app, FakeChatModel(ConnectionError("upstream overloaded")))
    report = upload(login("research_analyst")).json()
    assert report["extraction_status"] == "failed"
    ex = extraction_exchange(app, login, report)
    assert ex["outcome"] == "error" and "ConnectionError" in ex["error"] and "upstream overloaded" in ex["error"]
    assert ex["messages"] and ex["raw_reply"] is None and ex["parsed_content"] is None
    assert ex["graph_node"] == "generate" and isinstance(ex["latency_ms"], int)
    with app.state.session_factory() as db:
        assert db.execute(text("SELECT count(*) FROM llm_exchanges")).scalar() == 1


def test_an_exchange_that_cannot_be_stored_fails_the_call_closed(app, login):
    model = serve_chat(app, FakeChatModel(REPLY))
    app.state.llm.session_factory = unwritable_store
    report = upload(login("research_analyst")).json()
    assert len(model.requests) == 1  # the model answered; capture failed afterwards
    assert report["extraction_status"] == "failed" and report["insights"] == []
    assert "could not be recorded" in report["extraction_error"]
    assert "exchanges" not in extraction_event(app, report["id"])  # nothing was stored, so nothing to point at
    assert login("auditor").get("/api/audit/verify").json()["valid"]


def test_calls_through_a_trajectory_view_share_one_trajectory_in_call_order(app, login):
    from app.llm import LlmRequest

    serve_chat(app, FakeChatModel(then={"answer": "ok"}))
    turn = app.state.llm.trajectory()
    request = LlmRequest("research_tilt", "research_tilt@v1", "system", "user", {"type": "object"})
    first, second = turn.complete(request), turn.complete(request)
    auditor = login("auditor")
    exchanges = [auditor.get(f"/api/llm/exchanges/{r.exchange_id}").json() for r in (first, second)]
    assert exchanges[0]["trajectory_id"] == exchanges[1]["trajectory_id"] is not None
    assert [e["trajectory_position"] for e in exchanges] == [0, 1]
    alone = app.state.llm.complete(request)  # a plain call is a Trajectory of one
    assert auditor.get(f"/api/llm/exchanges/{alone.exchange_id}").json()["trajectory_position"] == 0


def test_an_exchange_with_no_graph_node_hashes_as_rows_written_before_graph_nodes(app):
    """Old rows have no Graph Node; the digest leaves an empty one out, so their stored hashes still verify."""
    row = LlmExchangeRow(
        created_at="2026-01-01T00:00:00.000000Z",
        task="t",
        prompt_version="t@v1",
        model="m",
        mode="recorded",
        endpoint_host=None,
        system_text="s",
        user_prompt="u",
        reply_schema_json="{}",
        outcome="ok",
        hash="",
    )
    before = exchange_digest(row)
    row.graph_node = "generate"
    assert exchange_digest(row) != before
    row.graph_node = None
    assert exchange_digest(row) == before
