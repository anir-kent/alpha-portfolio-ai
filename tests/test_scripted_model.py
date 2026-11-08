"""Seam: the scripted-model test helper (`tests.scripted`). It scripts the replies and tool calls of a multi-request
LLM Trajectory on pydantic-ai's function model and keeps every request it received, so a test fakes the LLM at the one
seam, the pydantic-ai Model (ADR-0010; spec: Testing Decisions)."""

from pathlib import Path

import pytest
from pydantic_ai import Agent
from sqlalchemy.orm import sessionmaker

from app.db import make_session_factory
from app.exchanges import ModelLlm
from app.llm import LlmError, LlmRequest
from tests.scripted import ByTask, ScriptedModel, ScriptedRequest, call


def store(tmp_path: Path) -> sessionmaker:
    return make_session_factory(f"sqlite:///{tmp_path / 'exchanges.db'}")


def lookup_agent(model: ScriptedModel) -> Agent:
    agent = Agent(model, instructions="Answer from the lookups.")

    @agent.tool_plain
    async def look_up_portfolio(portfolio_id: int) -> str:
        """The Portfolio's Screen Context."""
        return f"portfolio {portfolio_id}: 14 holdings"

    return agent


def test_a_scripted_trajectory_answers_each_request_in_turn_running_the_scripted_tool_calls():
    model = ScriptedModel(call("look_up_portfolio", portfolio_id=12), "Portfolio 12 holds 14 positions.")
    result = lookup_agent(model).run_sync("How many holdings?")

    assert result.output == "Portfolio 12 holds 14 positions."
    assert len(model.requests) == 2
    first, second = model.requests
    assert first.user_prompt == "How many holdings?" and first.instructions == "Answer from the lookups."
    assert [t.name for t in first.tools] == ["look_up_portfolio"]
    assert first.tool_returns == {}
    assert second.tool_returns == {"look_up_portfolio": "portfolio 12: 14 holdings"}


def test_a_scripted_reply_object_is_sent_as_its_json_text():
    model = ScriptedModel({"insights": []})
    assert Agent(model).run_sync("q").output == '{"insights": []}'


def test_a_scripted_exception_is_raised_by_its_request():
    model = ScriptedModel(RuntimeError("connection reset"))
    with pytest.raises(RuntimeError, match="connection reset"):
        Agent(model).run_sync("q")
    assert len(model.requests) == 1


def test_a_scripted_step_can_be_computed_from_the_request_it_answers():
    model = ScriptedModel(lambda request: {"echo": request.user_prompt})
    assert Agent(model).run_sync("hello").output == '{"echo": "hello"}'


def test_a_request_beyond_the_script_fails_the_test_rather_than_inventing_a_reply():
    model = ScriptedModel("only one")
    agent = Agent(model)
    agent.run_sync("first")
    with pytest.raises(pytest.fail.Exception, match="script has 1 step"):
        agent.run_sync("second")


def test_a_then_step_answers_every_request_after_the_script() -> None:
    model = ScriptedModel("first", then=lambda request: f"again: {request.user_prompt}")
    agent = Agent(model)
    assert [agent.run_sync(q).output for q in ("a", "b", "c")] == ["first", "again: b", "again: c"]


def step_call(task: str, user: str = "{}") -> LlmRequest:
    return LlmRequest(task, f"{task}@v1", "Reply in JSON.", user, {"type": "object", "properties": {"n": {}}})


def test_behind_capture_a_request_knows_its_steps_task_prompt_version_and_reply_schema(tmp_path: Path) -> None:
    model = ScriptedModel({"n": 1})
    ModelLlm(model, store(tmp_path), mode="recorded").complete(step_call("research_tilt"))
    (request,) = model.requests
    assert (request.task, request.prompt_version) == ("research_tilt", "research_tilt@v1")
    assert request.schema is not None and request.schema["properties"] == {"n": {}}
    assert (request.instructions or "").startswith("Reply in JSON.")


def test_by_task_answers_a_scripted_task_from_its_script_and_passes_any_other_on(tmp_path: Path) -> None:
    fallback = ScriptedModel(then={"from": "fallback"}, model_name="fallback")
    routed = ByTask(fallback, research_tilt=ScriptedModel(then={"from": "script"}, model_name="script"))
    llm = ModelLlm(routed, store(tmp_path), mode="recorded")

    tilt, other = llm.complete(step_call("research_tilt")), llm.complete(step_call("insight_extraction"))
    assert (tilt.content, tilt.model) == ({"from": "script"}, "script")
    assert (other.content, other.model) == ({"from": "fallback"}, "fallback")
    assert routed.tasks == ["research_tilt", "insight_extraction"]


def test_an_exhausted_script_fails_the_test_even_behind_capture(tmp_path: Path) -> None:
    model = ScriptedModel({"n": 1})
    llm = ModelLlm(model, store(tmp_path), mode="recorded")
    llm.complete(step_call("research_tilt"))
    with pytest.raises(pytest.fail.Exception, match="script has 1 step"):
        llm.complete(step_call("research_tilt"))


def test_a_script_callback_assertion_fails_the_test_even_behind_capture(tmp_path: Path) -> None:
    def wrong_request(request: ScriptedRequest) -> dict:
        assert request.task == "expected_task", "unexpected task"
        return {"n": 1}

    llm = ModelLlm(ScriptedModel(wrong_request), store(tmp_path), mode="recorded")
    with pytest.raises(pytest.fail.Exception, match="unexpected task"):
        llm.complete(step_call("research_tilt"))


def test_an_intentionally_scripted_provider_error_is_captured_as_an_llm_failure(tmp_path: Path) -> None:
    llm = ModelLlm(ScriptedModel(RuntimeError("provider broke")), store(tmp_path), mode="recorded")
    with pytest.raises(LlmError, match="provider broke") as failed:
        llm.complete(step_call("research_tilt"))
    assert failed.value.exchange_id is not None


def test_an_invalid_script_callback_reply_fails_the_test_even_behind_capture(tmp_path: Path) -> None:
    llm = ModelLlm(ScriptedModel(lambda request: None), store(tmp_path), mode="recorded")
    with pytest.raises(pytest.fail.Exception, match="not a script step"):
        llm.complete(step_call("research_tilt"))
