"""Assistant API tracer bullet: permission checked tool results, grounding and audit trajectories."""

import inspect
import json

import httpx
import pytest

from app.llm import RecordingMissing
from tests.scripted import ScriptedModel, call, serve
from tests.test_assistant import answer, ask, events, model  # noqa: F401 (imported fixtures)
from tests.test_queue import seeded  # noqa: F401 (imported fixtures)

QUEUE = {"kind": "queue", "entity_ids": {"sort": "score"}, "selected_item": None}


def test_cross_screen_lookup_grounds_figures_and_preserves_the_trajectory(app, login, model):
    advisor = login("advisor")
    detail = advisor.get("/api/portfolios/C001").json()
    reply = answer("Here is the looked-up Portfolio.")
    reply["claims"] = [
        {
            "text": f"Total value is {detail['total_value']}.",
            "citations": [{"kind": "engine", "figure": "portfolio.C001.total_value"}],
        },
        {
            "text": "Total value is 987654321.",
            "citations": [{"kind": "engine", "figure": "portfolio.C001.total_value"}],
        },
    ]
    script = serve(app, ScriptedModel(call("look_up_portfolio", portfolio_id="C001"), reply, answer("Next answer")))
    turn = ask(advisor, "Look up Portfolio C001", QUEUE).json()
    assert turn["outcome"] == "answered", turn
    assert [c["grounded"] for c in turn["answer"]["claims"]] == [True, False]
    trajectory = turn["trajectory"]
    assert trajectory["requests_used"] == 2 and trajectory["request_limit"] >= 2
    assert [s["kind"] for s in trajectory["steps"]] == ["model_request", "tool_call", "model_request"]
    tool = trajectory["steps"][1]
    assert tool["name"] == "look_up_portfolio" and tool["arguments"] == {"portfolio_id": "C001"}
    assert "C001" in tool["result_summary"] and "holdings" in tool["result_summary"]
    assert "SCREEN CONTEXT" not in json.dumps(trajectory) and "answer_markdown" not in json.dumps(trajectory)
    assert trajectory["input_tokens"] > 0 and trajectory["output_tokens"] > 0
    result = script.requests[1].tool_returns["look_up_portfolio"]
    assert isinstance(result, str) and '"portfolio_id":"C001"' in result
    assert advisor.get("/api/assistant/conversation").json()["turns"][0]["trajectory"] == trajectory
    event = events(app, "assistant.answered")[-1]
    assert len(event["exchanges"]) == 2
    assert event["exchanges"][-1]["exchange_id"] == turn["exchange_id"]
    auditor = login("auditor")
    exchange = auditor.get(f"/api/llm/exchanges/{turn['exchange_id']}").json()
    assert "look_up_portfolio" in json.dumps(exchange["messages"])
    assert "portfolio.C001.total_value" in json.dumps(exchange["messages"])
    assert auditor.get("/api/audit/verify").json()["valid"]
    ask(advisor, "What did you find?", QUEUE)
    assert not script.requests[-1].tool_returns
    assert "CONVERSATION SO FAR" in script.requests[-1].user_prompt


@pytest.mark.parametrize(
    "role,screen,portfolio_id",
    [
        ("platform_owner", {"kind": "health", "entity_ids": {}}, "C001"),
        ("advisor", QUEUE, "does-not-exist"),
    ],
)
def test_forbidden_and_missing_lookups_return_the_same_safe_result(app, login, model, role, screen, portfolio_id):
    script = serve(app, ScriptedModel(call("look_up_portfolio", portfolio_id=portfolio_id), answer("Not permitted.")))
    turn = ask(login(role), "Look up that Portfolio", screen).json()
    assert turn["outcome"] == "answered", turn
    assert turn["answer"]["markdown"] == "Not permitted."
    assert script.requests[1].tool_returns == {"look_up_portfolio": "not found or not permitted for your role"}
    assert turn["trajectory"]["steps"][1]["result_summary"] == "not found or not permitted for your role"


@pytest.mark.parametrize(
    "failure,reason",
    [
        (httpx.ConnectError("down"), "llm_error"),
        (RecordingMissing("no recording"), "replay_miss"),
        ({"unexpected": "shape"}, "unreadable_reply"),
        ("not JSON", "llm_error"),
    ],
)
def test_failure_on_the_second_request_anchors_both_exchanges(app, login, model, failure, reason):
    serve(app, ScriptedModel(call("look_up_portfolio", portfolio_id="C001"), failure))
    turn = ask(login("advisor"), "Look it up", QUEUE).json()
    assert turn["outcome"] == "failed", turn
    event = events(app, "assistant.failed")[-1]
    assert event["reason"] == reason
    assert len(event["exchanges"]) == 2
    assert turn["trajectory"]["requests_used"] == 2
    assert login("auditor").get("/api/audit/verify").json()["valid"]


def test_all_registered_assistant_tools_are_coroutines():
    from pydantic_ai.toolsets import FunctionToolset

    from app import prompts
    from app.assistant_agent import build_agent
    from app.llm import LlmRequest

    prompt = prompts.ASSISTANT_ANSWER
    request = LlmRequest(prompt.name, prompt.label, prompt.system, "Question", prompts.ASSISTANT_REPLY_SCHEMA)
    agent = build_agent(ScriptedModel(), request)
    tools = [
        tool for toolset in agent.toolsets if isinstance(toolset, FunctionToolset) for tool in toolset.tools.values()
    ]
    assert tools
    assert all(inspect.iscoroutinefunction(tool.function) for tool in tools)
    assert all(tool.max_retries == 0 for tool in tools)


def test_one_request_answer_has_a_summary_and_suggested_questions_drop_tool_history(app, login, model):
    script = serve(
        app, ScriptedModel(call("look_up_portfolio", portfolio_id="C001"), answer("Earlier answer"), answer())
    )
    advisor = login("advisor")
    ask(advisor, "Look it up", QUEUE)
    question = advisor.get("/api/assistant/suggested-questions", params={"kind": "queue"}).json()["questions"][0]
    turn = ask(advisor, question, QUEUE).json()
    assert turn["outcome"] == "answered"
    assert turn["trajectory"]["requests_used"] == 1
    assert [s["kind"] for s in turn["trajectory"]["steps"]] == ["model_request"]
    assert "CONVERSATION SO FAR" not in script.requests[-1].user_prompt
    assert not script.requests[-1].tool_returns


def test_invalid_lookup_arguments_fail_without_a_retry(app, login, model):
    script = serve(app, ScriptedModel(call("look_up_portfolio")))
    turn = ask(login("advisor"), "Look it up", QUEUE).json()
    assert turn["outcome"] == "failed"
    assert len(script.requests) == turn["trajectory"]["requests_used"] == 1


def test_recorded_suggested_lookup_replays_and_changed_tool_result_misses(app, login, model, tmp_path):
    from app.db import ClientRow
    from app.pydantic_llm import RecordingModel, ReplayModel

    question = (
        login("advisor").get("/api/assistant/suggested-questions", params={"kind": "queue"}).json()["questions"][2]
    )
    scripted = ScriptedModel(call("look_up_portfolio", portfolio_id="C001"), answer("Looked up C001"))
    serve(app, RecordingModel(scripted, tmp_path))
    recorded = ask(login("advisor"), question, QUEUE).json()
    assert recorded["outcome"] == "answered"
    replay = serve(app, ReplayModel(tmp_path, model_name="scripted"))
    replayed = ask(login("advisor"), question, QUEUE).json()
    assert replayed["answer"] == recorded["answer"]
    assert replayed["trajectory"] == recorded["trajectory"]
    assert replay.answered == 2
    with app.state.session_factory() as db:
        client = db.get(ClientRow, "C001")
        client.horizon_years += 1
        db.commit()
    missed = ask(login("advisor"), question, QUEUE).json()
    assert missed["outcome"] == "failed"
    assert events(app, "assistant.failed")[-1]["reason"] == "replay_miss"
    assert missed["trajectory"]["requests_used"] == 2


def test_lookup_keeps_screen_figures_and_other_portfolios_distinct(app, login, model):
    from tests.test_assistant import portfolio_screen

    advisor = login("advisor")
    first = advisor.get("/api/portfolios/C001").json()["total_value"]
    second = advisor.get("/api/portfolios/C002").json()["total_value"]
    assert first != second
    reply = answer("Values of both Portfolios")
    reply["claims"] = [
        {"text": f"Screen total value is {first}.", "citations": [{"kind": "engine", "figure": "total_value"}]},
        {
            "text": f"Lookup total value is {second}.",
            "citations": [{"kind": "engine", "figure": "portfolio.C002.total_value"}],
        },
        {"text": f"Screen total value is {second}.", "citations": [{"kind": "engine", "figure": "total_value"}]},
    ]
    serve(app, ScriptedModel(call("look_up_portfolio", portfolio_id="C002"), reply))
    turn = ask(advisor, "Compare these Portfolios", portfolio_screen("C001")).json()
    assert [c["grounded"] for c in turn["answer"]["claims"]] == [True, True, False]


def test_committed_suggested_lookup_replays_a_grounded_two_request_answer(app, login):
    from tests.fixtures.suggested_questions import seed_demo

    seed_demo(app)
    advisor = login("advisor")
    question = advisor.get("/api/assistant/suggested-questions", params={"kind": "queue"}).json()["questions"][2]
    turn = ask(advisor, question, QUEUE).json()
    assert turn["outcome"] == "answered", turn
    assert turn["trajectory"]["requests_used"] == 2
    assert turn["trajectory"]["steps"][1]["name"] == "look_up_portfolio"
    assert turn["answer"]["claims"] and all(claim["grounded"] for claim in turn["answer"]["claims"])


def test_committed_offline_restriction_answer_addresses_the_question(app, login):
    from tests.fixtures.suggested_questions import seed_demo
    from tests.test_assistant import portfolio_screen

    seed_demo(app)
    advisor = login("advisor")
    question = advisor.get("/api/assistant/suggested-questions", params={"kind": "portfolio"}).json()["questions"][2]
    turn = ask(advisor, question, portfolio_screen("C004")).json()
    assert turn["outcome"] == "answered", turn
    assert "Restrictions" in turn["answer"]["markdown"] and "XOM" in turn["answer"]["markdown"]
