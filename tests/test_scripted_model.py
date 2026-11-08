"""Seam: the scripted-model test helper (`tests.scripted`). It scripts the replies and tool calls of a multi-request
LLM Trajectory on pydantic-ai's function model and keeps every request it received, so a test fakes the LLM at the one
seam, the pydantic-ai Model (ADR-0010; spec: Testing Decisions)."""

import pytest
from pydantic_ai import Agent

from tests.scripted import ScriptedModel, call


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
    with pytest.raises(AssertionError, match="script has 1 step"):
        agent.run_sync("second")
