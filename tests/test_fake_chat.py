"""Seam: the fake chat model (`tests.fake_chat`) behind the step-facing `complete` (ADR-0011). It scripts the pipeline
LLM Graph's replies and keeps every request it received, so a test fakes the LLM at the one seam the pipeline has,
the chat model `get_chat_model` would build."""

from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall

from app.db import make_session_factory
from app.exchanges import ModelLlm
from app.llm import LlmError, LlmRequest
from tests.fake_chat import ByTask, ChatRequest, FakeChatModel


def llm(tmp_path: Path, chat_model: FakeChatModel) -> ModelLlm:
    store = make_session_factory(f"sqlite:///{tmp_path / 'exchanges.db'}")
    # No Assistant Model: only the pipeline's `complete` is exercised.
    return ModelLlm(None, store, mode="recorded", chat_model=chat_model)  # type: ignore[arg-type]


def step_call(task: str, user: str = "{}") -> LlmRequest:
    return LlmRequest(task, f"{task}@v1", "Reply in JSON.", user, {"type": "object", "properties": {"n": {}}})


def test_a_request_knows_its_steps_task_prompt_version_reply_schema_and_graph_node(tmp_path: Path) -> None:
    model = FakeChatModel({"n": 1})
    llm(tmp_path, model).complete(step_call("research_tilt"))
    (request,) = model.requests
    assert (request.task, request.prompt_version) == ("research_tilt", "research_tilt@v1")
    assert request.metadata["langgraph_node"] == "generate"
    assert request.response_format["json_schema"]["schema"]["properties"] == {"n": {}}
    assert request.step_call() == step_call("research_tilt")  # the step call, recovered from what was sent


def test_a_scripted_step_can_be_computed_from_the_request_it_answers(tmp_path: Path) -> None:
    model = FakeChatModel(lambda request: {"echo": request.user_prompt})
    assert llm(tmp_path, model).complete(step_call("t", "hello")).content == {"echo": "hello"}


def test_a_then_step_answers_every_request_after_the_script(tmp_path: Path) -> None:
    client = llm(tmp_path, FakeChatModel({"n": 1}, then=lambda request: {"n": len(request.user_prompt)}))
    assert [client.complete(step_call("t", u)).content for u in ("a", "bb", "ccc")] == [{"n": 1}, {"n": 2}, {"n": 3}]


def test_by_task_answers_a_scripted_task_from_its_fake_and_passes_any_other_on(tmp_path: Path) -> None:
    fallback = FakeChatModel(then={"from": "fallback"}, model_name="fallback")
    routed = ByTask(fallback, research_tilt=FakeChatModel(then={"from": "script"}, model_name="script"))
    client = llm(tmp_path, routed)
    tilt, other = client.complete(step_call("research_tilt")), client.complete(step_call("insight_extraction"))
    assert (tilt.content, tilt.model) == ({"from": "script"}, "script")
    assert (other.content, other.model) == ({"from": "fallback"}, "fallback")
    assert routed.tasks == ["research_tilt", "insight_extraction"]


def test_an_exhausted_script_fails_the_test_even_behind_capture(tmp_path: Path) -> None:
    client = llm(tmp_path, FakeChatModel({"n": 1}))
    client.complete(step_call("research_tilt"))
    with pytest.raises(pytest.fail.Exception, match="script has 1 step"):
        client.complete(step_call("research_tilt"))


def test_a_script_callback_assertion_fails_the_test_even_behind_capture(tmp_path: Path) -> None:
    def wrong_request(request: ChatRequest) -> dict:
        assert request.task == "expected_task", "unexpected task"
        return {"n": 1}

    with pytest.raises(pytest.fail.Exception, match="unexpected task"):
        llm(tmp_path, FakeChatModel(wrong_request)).complete(step_call("research_tilt"))


def test_an_intentionally_scripted_provider_error_is_captured_as_an_llm_failure(tmp_path: Path) -> None:
    with pytest.raises(LlmError, match="provider broke") as failed:
        llm(tmp_path, FakeChatModel(RuntimeError("provider broke"))).complete(step_call("research_tilt"))
    assert failed.value.exchange_id is not None


def test_an_invalid_script_step_fails_the_test_even_behind_capture(tmp_path: Path) -> None:
    with pytest.raises(pytest.fail.Exception, match="not a script step"):
        llm(tmp_path, FakeChatModel(lambda request: None)).complete(step_call("research_tilt"))


def test_it_scripts_a_tool_calling_turn_as_the_documented_fake_does() -> None:
    """`bind_tools` returns the model, so a scripted tool call reaches the caller (ticket 03 builds on this)."""
    turn = AIMessage(content="", tool_calls=[ToolCall(name="look_up_portfolio", args={"portfolio_id": "C001"}, id="1")])
    model = FakeChatModel(turn, "Done.")
    bound = model.bind_tools([])
    assert bound.invoke([HumanMessage("q")]).tool_calls[0]["name"] == "look_up_portfolio"
    assert bound.invoke([HumanMessage("q")]).content == "Done."
