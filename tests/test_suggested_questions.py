"""Seam: Suggested Questions through the HTTP API (sme-assistant spec: API contract). They are plain shortcuts: the
drawer offers three per screen kind and asking one is asking an ordinary Question."""

import pytest

from app.main import create_app
from tests.conftest import ROLES
from tests.fixtures.demo import demo_screens, demo_settings, lift_question_limits, seed_demo
from tests.fixtures.demo import login as demo_login
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


def test_a_failed_suggested_question_gives_the_ordinary_failure_message(login, model):
    model.error = "upstream unavailable"
    advisor = login("advisor")
    (question, *_) = suggested(advisor, "portfolio")
    turn = ask(advisor, question, portfolio_screen("C001")).json()
    assert turn["message"] == "The Assistant couldn't answer, try again."
    assert advisor.get("/api/assistant/conversation").json()["turns"][0]["message"] == turn["message"]


def _seeded_demo_prompts(directory) -> list[tuple[str, str, str]]:
    """(role, screen kind, prompt) for every Suggested Question on every demo screen, on a freshly seeded app."""
    directory.mkdir()
    app = create_app(lift_question_limits(demo_settings(directory)))
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


def test_every_suggested_question_on_every_demo_screen_is_answered_like_any_other_question(app, demo):
    fake = serve(app, AnsweringModel(answer()))
    for role in ROLES:
        c = demo_login(app, role)
        for screen in demo_screens(app):
            for question in suggested(c, screen["kind"]):
                before = len(fake.requests)
                turn = ask(c, question, screen).json()
                assert turn["outcome"] in ("answered", "refused"), (role, screen, question, turn["message"])
                # The only refusals are of roles that cannot read the screen, made before any model call.
                assert turn["outcome"] == "answered" or len(fake.requests) == before, (role, screen, question)
                if turn["outcome"] == "answered":
                    assert turn["answer"]["markdown"] and turn["exchange_id"] is not None
    assert not events(app, "assistant.failed")
    assert events(app, "assistant.answered")
