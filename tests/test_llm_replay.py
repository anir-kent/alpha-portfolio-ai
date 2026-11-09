"""Seam: the replay Model (ADR-0010; spec: Replay). Recorded mode answers each model request from a recording keyed by
the task, prompt version, reply schema, tool definitions and the full message list so far; a miss is the
recording-missing error, never a guess. Live mode with a record directory writes recordings in that format, one per
model request. No network: live calls go to an `httpx.MockTransport`."""

import dataclasses
import json

import httpx
import pytest
from pydantic_ai import Agent
from pydantic_ai.models import override_allow_model_requests

from app.db import make_session_factory
from app.exchanges import ModelLlm, build_llm
from app.llm import LlmError, LlmRequest, RecordingMissing
from app.pydantic_llm import RecordingModel, ReplayModel, build_live_model, tagged
from tests.chat_completions import completion
from tests.scripted import ScriptedModel, call

REQUEST = LlmRequest(
    task="insight_extraction",
    prompt_version="insight_extraction@v1",
    system="Extract the insights.",
    user="Page 1: We are constructive on technology.",
    schema={"type": "object", "properties": {"insights": {"type": "array"}}, "required": ["insights"]},
)
REPLY = {"insights": [{"subject": "Information Technology"}]}


@pytest.fixture
def store(tmp_path):
    return make_session_factory(f"sqlite:///{tmp_path / 'exchanges.db'}")


@pytest.fixture
def recordings(tmp_path):
    return tmp_path / "recordings"


def record(store, recordings, *steps, request=REQUEST):
    """Makes `request` through a scripted Model with recording on, as live mode with a record directory does."""
    return ModelLlm(
        RecordingModel(ScriptedModel(*steps, model_name="gw/model"), recordings), store, mode="live"
    ).complete(request)


def replay(store, recordings, request=REQUEST):
    return ModelLlm(ReplayModel(recordings, model_name="gw/model"), store, mode="recorded").complete(request)


def test_a_recorded_request_replays_its_reply_with_no_model_behind_it(store, recordings):
    record(store, recordings, REPLY)
    response = replay(store, recordings)
    assert response.content == REPLY
    assert response.model == "gw/model"
    assert response.exchange_id is not None


def test_each_model_request_is_one_recording(store, recordings):
    record(store, recordings, REPLY)
    record(store, recordings, {"insights": []}, request=dataclasses.replace(REQUEST, user="Page 1: Another report."))
    assert len(list(recordings.glob("insight_extraction-*.request.json"))) == 2


@pytest.mark.parametrize(
    "change",
    [
        {"system": "Extract the insights, carefully."},
        {"user": "Page 1: We are cautious on technology."},
        {"prompt_version": "insight_extraction@v2"},
        {"schema": {**REQUEST.schema, "required": []}},
        {"task": "research_tilt"},
    ],
    ids=["system text", "user prompt", "prompt version", "reply schema", "task"],
)
def test_a_changed_request_misses_its_recording_instead_of_replaying_a_stale_reply(store, recordings, change):
    record(store, recordings, REPLY)
    with pytest.raises(LlmError, match="No recorded response") as raised:
        replay(store, recordings, dataclasses.replace(REQUEST, **change))
    assert isinstance(raised.value.__cause__, RecordingMissing)
    assert raised.value.exchange_id is not None  # the miss is an error Exchange, as any failed call


def lookup_agent(model, *, description="The Portfolio's Screen Context.", holdings=14) -> Agent:
    agent = Agent(model, instructions="Answer from the lookups.")

    async def look_up_portfolio(portfolio_id: int) -> str:
        return f"portfolio {portfolio_id}: {holdings} holdings"

    look_up_portfolio.__doc__ = description
    agent.tool_plain(look_up_portfolio)
    return agent


def run_trajectory(model, **agent_options) -> str:
    with tagged(REQUEST):
        return lookup_agent(model, **agent_options).run_sync("How many holdings?").output


def test_a_recorded_trajectory_replays_request_by_request_through_its_tool_calls(recordings):
    script = ScriptedModel(call("look_up_portfolio", portfolio_id=12), "Portfolio 12 holds 14 positions.")
    assert run_trajectory(RecordingModel(script, recordings)) == "Portfolio 12 holds 14 positions."
    assert len(list(recordings.glob("*.request.json"))) == 2
    assert run_trajectory(ReplayModel(recordings, model_name="gw/model")) == "Portfolio 12 holds 14 positions."


def test_a_changed_tool_definition_misses_the_first_request(recordings):
    script = ScriptedModel(call("look_up_portfolio", portfolio_id=12), "Portfolio 12 holds 14 positions.")
    run_trajectory(RecordingModel(script, recordings))
    with pytest.raises(RecordingMissing):
        run_trajectory(ReplayModel(recordings, model_name="gw/model"), description="Another description.")


def test_a_changed_tool_result_misses_the_continuation_instead_of_replaying_it(recordings):
    script = ScriptedModel(call("look_up_portfolio", portfolio_id=12), "Portfolio 12 holds 14 positions.")
    run_trajectory(RecordingModel(script, recordings))
    replaying = ReplayModel(recordings, model_name="gw/model")
    with pytest.raises(RecordingMissing):
        run_trajectory(replaying, holdings=15)
    assert replaying.answered == 1  # the first request still replayed; only the continuation missed


def live_settings(settings, recordings, **extra):
    return settings.model_copy(
        update={
            "llm_mode": "live",
            "llm_api_key": "sk-test",
            "llm_base_url": "https://openrouter.ai/api/v1/",
            "llm_model": "anthropic/claude-sonnet-5.5",
            "llm_record": True,
            "llm_recordings_dir": str(recordings),
            **extra,
        }
    )


def test_a_live_call_with_a_record_directory_replays_in_recorded_mode(settings, store, recordings):
    sent = []

    def provider(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return completion(json.dumps(REPLY))

    live = live_settings(settings, recordings)
    with override_allow_model_requests(True):
        assert build_llm(live, store, httpx.MockTransport(provider)).complete(REQUEST).content == REPLY
    assert len(sent) == 1

    recorded = settings.model_copy(update={"llm_recordings_dir": str(recordings)})
    response = build_llm(recorded, store).complete(REQUEST)
    assert response.content == REPLY and response.model == "anthropic/claude-sonnet-5.5"
    assert len(sent) == 1  # nothing crossed the wire on replay


def test_real_model_requests_are_blocked_in_the_test_suite(settings, store, recordings):
    def provider(request: httpx.Request) -> httpx.Response:
        raise AssertionError("a real model request was made")

    model = build_live_model(live_settings(settings, recordings), httpx.MockTransport(provider))
    with pytest.raises(LlmError, match="ALLOW_MODEL_REQUESTS"):
        ModelLlm(model, store, mode="live").complete(REQUEST)
