"""The request budget per Answer (ADR-0010): a Trajectory that keeps asking for lookups is stopped at the limit, the
turn fails with `budget_exhausted`, and every Exchange it made stays anchored in its `assistant.failed` event."""

from tests.scripted import ScriptedModel, call, serve
from tests.test_assistant import answer, ask, events, model  # noqa: F401 (imported fixtures)
from tests.test_queue import seeded  # noqa: F401 (imported fixtures)

QUEUE = {"kind": "queue", "entity_ids": {"sort": "score"}, "selected_item": None}
BUDGET_MESSAGE = "That Question needed more lookups than one Answer may make. Try a narrower Question."


def runaway():
    """A Model that asks for another lookup on every request."""
    return ScriptedModel(then=call("look_up_portfolio", portfolio_id="C001"))


def test_a_trajectory_that_keeps_calling_tools_fails_at_the_default_limit_with_every_exchange_anchored(
    app, login, model, settings
):
    assert settings.assistant_request_limit == 6
    script = serve(app, runaway())
    advisor = login("advisor")
    turn = ask(advisor, "Look at everything", QUEUE).json()
    assert turn["outcome"] == "failed" and turn["answer"] is None, turn
    assert turn["message"] == BUDGET_MESSAGE
    assert len(script.requests) == 6  # the seventh request is never sent
    trajectory = turn["trajectory"]
    assert trajectory["requests_used"] == 6 and trajectory["request_limit"] == 6
    assert [s["kind"] for s in trajectory["steps"]] == ["model_request", "tool_call"] * 6
    (event,) = events(app, "assistant.failed")
    assert event["reason"] == "budget_exhausted"
    ids = [e["exchange_id"] for e in event["exchanges"]]
    assert len(ids) == 6 and ids == sorted(ids) and ids[-1] == turn["exchange_id"]
    (reloaded,) = advisor.get("/api/assistant/conversation").json()["turns"]
    assert (
        reloaded["outcome"] == "failed"
        and reloaded["message"] == BUDGET_MESSAGE
        and reloaded["trajectory"] == trajectory
    )
    auditor = login("auditor")
    assert auditor.get("/api/audit/verify").json()["valid"]
    positions = [auditor.get(f"/api/llm/exchanges/{i}").json()["trajectory_position"] for i in ids]
    assert positions == sorted(positions)


def test_the_limit_is_a_setting(app, login, model, settings):
    settings.assistant_request_limit = 2
    script = serve(app, runaway())
    turn = ask(login("advisor"), "Look at everything", QUEUE).json()
    assert turn["outcome"] == "failed" and len(script.requests) == 2
    assert turn["trajectory"]["requests_used"] == 2 and turn["trajectory"]["request_limit"] == 2
    (event,) = events(app, "assistant.failed")
    assert event["reason"] == "budget_exhausted" and len(event["exchanges"]) == 2


def test_a_turn_exactly_at_the_limit_is_answered(app, login, model, settings):
    settings.assistant_request_limit = 2
    script = serve(app, ScriptedModel(call("look_up_portfolio", portfolio_id="C001"), answer("Found it.")))
    turn = ask(login("advisor"), "Look up Portfolio C001", QUEUE).json()
    assert turn["outcome"] == "answered", turn
    assert turn["answer"]["markdown"] == "Found it." and len(script.requests) == 2
    assert turn["trajectory"]["requests_used"] == 2 and turn["trajectory"]["request_limit"] == 2
    assert events(app, "assistant.failed") == []


def test_the_model_card_shows_the_request_limit(login, settings):
    settings.assistant_request_limit = 4
    card = login("auditor").get("/api/governance").json()["model_card"]
    assert card["assistant"]["limits"]["request_limit"] == 4
