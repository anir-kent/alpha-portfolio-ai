"""Seam: Suggested Questions and replay mode through the HTTP API (sme-assistant spec: Replay mode, API contract).

Replay tests run in the default recorded mode against the committed recordings in `tests/fixtures/llm`, made by
`uv run python -m tests.fixtures.suggested_questions` against the same seeded data `seed_demo` builds."""

import pytest

from app.main import create_app
from tests.conftest import ROLES
from tests.fixtures.suggested_questions import demo_screens, lift_question_limits, replay_settings, seed_demo
from tests.fixtures.suggested_questions import login as demo_login
from tests.scripted import serve
from tests.test_assistant import AnsweringModel, answer, ask, events, model, portfolio_screen  # noqa: F401  (fixture)
from tests.test_queue import seeded  # noqa: F401  (fixture)

SUGGESTED = "/api/assistant/suggested-questions"


def suggested(c, kind: str) -> list[str]:
    return c.get(SUGGESTED, params={"kind": kind}).json()["questions"]


KINDS = ["queue", "portfolio", "recommendation", "approvals", "audit", "exchanges", "governance", "config", "health"]


@pytest.mark.parametrize("kind", KINDS)
def test_every_screen_kind_offers_three_suggested_questions(login, kind):
    r = login("advisor").get(SUGGESTED, params={"kind": kind})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == kind
    questions = body["questions"]
    assert len(questions) == 3 and len(set(questions)) == 3
    assert all(isinstance(q, str) and q.strip() == q and q.endswith("?") for q in questions)


def test_suggested_questions_are_the_same_for_every_role(login):
    seen = {tuple(login(role).get(SUGGESTED, params={"kind": "portfolio"}).json()["questions"]) for role in ROLES}
    assert len(seen) == 1


def test_an_unknown_screen_kind_is_rejected(login):
    assert login("advisor").get(SUGGESTED, params={"kind": "nowhere"}).status_code == 422


def test_suggested_questions_need_a_login(client):
    assert client.get(SUGGESTED, params={"kind": "queue"}).status_code == 401


def test_a_suggested_question_is_asked_without_the_conversation_so_far_so_its_prompt_never_varies(login, model):
    advisor = login("advisor")
    (suggested, *_) = advisor.get(SUGGESTED, params={"kind": "portfolio"}).json()["questions"]
    ask(advisor, "Tell me about this client", portfolio_screen("C001"))
    ask(advisor, suggested, portfolio_screen("C001"))
    ask(login("advisor"), suggested, portfolio_screen("C001"))  # a fresh Conversation
    free_form, after_history, fresh = model.requests
    assert "CONVERSATION SO FAR" not in after_history.user_prompt
    assert after_history.user_prompt == fresh.user_prompt


def test_a_suggested_question_from_another_screen_kind_still_carries_the_conversation(login, model):
    advisor = login("advisor")
    (queue_question, *_) = advisor.get(SUGGESTED, params={"kind": "queue"}).json()["questions"]
    ask(advisor, "Tell me about this client", portfolio_screen("C001"))
    ask(advisor, queue_question, portfolio_screen("C001"))
    assert "CONVERSATION SO FAR" in model.requests[1].user_prompt


REPLAY_MESSAGE = "Only Suggested Questions work in replay mode."


def test_a_free_form_question_in_replay_mode_fails_with_the_replay_mode_message(app, login, seeded):  # noqa: F811
    advisor = login("advisor")
    turn = ask(advisor, "What colour is the sky?", portfolio_screen("C001")).json()
    assert turn["outcome"] == "failed" and turn["answer"] is None
    assert turn["message"] == REPLAY_MESSAGE
    (event,) = events(app, "assistant.failed")
    assert event["reason"] == "replay_miss" and event["exchanges"][0]["exchange_id"] == turn["exchange_id"]
    (stored,) = advisor.get("/api/assistant/conversation").json()["turns"]
    assert stored["message"] == REPLAY_MESSAGE


def test_a_failure_in_live_mode_keeps_the_ordinary_failure_message(login, model):
    model.error = "upstream unavailable"
    advisor = login("advisor")
    turn = ask(advisor, "Why?", portfolio_screen("C001")).json()
    assert turn["message"] == "The Assistant couldn't answer, try again."
    assert advisor.get("/api/assistant/conversation").json()["turns"][0]["message"] == turn["message"]


def _seeded_demo_prompts(directory) -> list[tuple[str, str, str]]:
    """(role, screen kind, prompt) for every Suggested Question on every demo screen, on a freshly seeded app."""
    directory.mkdir()
    app = create_app(lift_question_limits(replay_settings(directory)))
    seed_demo(app)
    fake = serve(app, AnsweringModel(answer()))
    asked = []
    for screen in demo_screens(app):
        for role in ROLES:
            c = demo_login(app, role)
            for question in suggested(c, screen["kind"]):
                before = len(fake.requests)
                ask(c, question, screen)
                if len(fake.requests) > before:  # a role that cannot read the screen is refused without a call
                    asked.append(
                        (role, screen["kind"], (fake.requests[-1].instructions or "") + fake.requests[-1].user_prompt)
                    )
    return asked


def test_every_demo_screen_context_is_byte_identical_across_freshly_seeded_databases(tmp_path):
    first, second = _seeded_demo_prompts(tmp_path / "one"), _seeded_demo_prompts(tmp_path / "two")
    assert {kind for _, kind, _ in first} == set(KINDS) - {"audit"}
    assert first == second


@pytest.fixture
def demo(app):
    lift_question_limits(app.state.settings)
    seed_demo(app)
    return app


def test_in_replay_mode_every_suggested_question_on_every_demo_screen_replays_its_answer(app, demo):
    for role in ROLES:
        c = demo_login(app, role)  # one Conversation per role: replays do not depend on what was asked before
        for screen in demo_screens(app):
            for question in suggested(c, screen["kind"]):
                turn = ask(c, question, screen).json()
                assert turn["outcome"] in ("answered", "refused"), (role, screen, question, turn["message"])
                # The only refusals are of roles that cannot read the screen, made before any model call.
                assert turn["outcome"] == "answered" or turn["exchange_id"] is None, (role, screen, question)
                if turn["outcome"] == "answered":
                    assert turn["answer"]["markdown"] and turn["exchange_id"] is not None
    assert not events(app, "assistant.failed")
    assert events(app, "assistant.answered")


def test_a_replayed_answer_offers_its_follow_up_questions_and_they_replay_only_if_suggested(app, demo):
    advisor = demo_login(app, "advisor")
    screen = {"kind": "portfolio", "entity_ids": {"portfolio_id": "C004"}, "selected_item": None}
    questions = suggested(advisor, "portfolio")
    question = questions[0]
    turn = ask(advisor, question, screen).json()
    assert turn["outcome"] == "answered" and turn["answer"]["follow_up_questions"]
    follow_up = next(q for q in turn["answer"]["follow_up_questions"] if q not in questions)
    assert ask(advisor, follow_up, screen).json()["message"] == REPLAY_MESSAGE


def test_audit_suggested_questions_cannot_replay_and_say_so(app, demo):
    auditor = demo_login(app, "auditor")
    screen: dict = {"kind": "audit", "entity_ids": {}, "selected_item": None}
    for question in suggested(auditor, "audit"):
        assert ask(auditor, question, screen).json()["message"] == REPLAY_MESSAGE
