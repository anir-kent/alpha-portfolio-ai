"""Seam: the Assistant through the HTTP API (sme-assistant spec, ADR-0006). The model is a prompt-capturing fake behind
the same capture wrapper the app uses, so every turn's Exchange is real; the captured request is the only window into
what the model saw."""

import json

import pytest
from sqlalchemy import select

from app.db import AuditEventRow, ClientRow
from app.exchanges import CapturingLlm
from app.llm import LlmRequest, LlmResponse
from app.seeder import PLANTED
from tests.runs import run_and_wait
from tests.test_portfolio import url
from tests.test_queue import seeded  # noqa: F401  (fixture)

ASK = "/api/assistant/questions"
REFUSAL_START = "I can only help with questions about this platform"


def answer(markdown="The Portfolio drifts most in equity.", *, in_scope=True, follow_ups=()):
    return {"in_scope": in_scope, "answer_markdown": markdown, "claims": [], "follow_up_questions": list(follow_ups)}


class PromptCapturingLlm:
    """Returns the scripted reply and keeps every request it received."""

    def __init__(self, reply: dict):
        self.reply = reply
        self.requests: list[LlmRequest] = []

    def complete(self, request):
        self.requests.append(request)
        return LlmResponse(self.reply, "fake-model-1", request.prompt_version)


@pytest.fixture
def model(app, login, seeded):  # noqa: F811
    """A completed Analysis Run, then a fake model answering every Assistant Question."""
    run_and_wait(login("advisor"))
    fake = PromptCapturingLlm(answer())
    app.state.llm = CapturingLlm(fake, app.state.session_factory, mode="recorded")
    return fake


def portfolio_screen(portfolio_id):
    return {"kind": "portfolio", "entity_ids": {"portfolio_id": portfolio_id}, "selected_item": None}


def ask(c, question, screen):
    return c.post(ASK, json={"question": question, "screen": screen})


def events(app, type_):
    with app.state.session_factory() as db:
        rows = db.scalars(select(AuditEventRow).where(AuditEventRow.type == type_).order_by(AuditEventRow.id)).all()
    return [json.loads(r.payload_json) for r in rows]


def test_an_advisor_asks_on_the_portfolio_screen_and_gets_a_markdown_answer(login, model):
    model.reply = answer("**Equity** drives the drift.", follow_ups=["Which Restriction applies?"])
    r = ask(login("advisor"), "Which asset class drives the drift?", portfolio_screen(PLANTED["restricted_breach"]))
    assert r.status_code == 200, r.text
    turn = r.json()
    assert turn["outcome"] == "answered" and turn["seq"] == 1
    assert turn["answer"]["markdown"] == "**Equity** drives the drift."
    assert turn["answer"]["follow_up_questions"] == ["Which Restriction applies?"]
    assert isinstance(turn["exchange_id"], int) and len(turn["exchange_hash"]) == 64
    (request,) = model.requests
    assert request.prompt_version == "assistant_answer@v1"
    assert "Which asset class drives the drift?" in request.user


def test_the_prompt_holds_the_portfolio_screen_context_from_the_portfolio_screen(login, model):
    advisor = login("advisor")
    cid = PLANTED["restricted_breach"]
    screen = advisor.get(url(cid)).json()
    ask(advisor, "Why is this one flagged?", portfolio_screen(cid))
    prompt = model.requests[0].user
    for h in screen["holdings"]:
        assert h["symbol"] in prompt
    for ac in screen["drift"]["asset_classes"]:
        assert f'"target_pct":{ac["target_pct"]}' in prompt and f'"drift_pp":{ac["drift_pp"]}' in prompt
    assert f'"portfolio_drift_pp":{screen["drift"]["portfolio_drift_pp"]}' in prompt
    assert '{"kind":"instrument","value":"XOM"}' in prompt
    assert f'"risk_profile":"{screen["client"]["risk_profile"]}"' in prompt
    assert f'"run_id":{screen["drift"]["run_id"]}' in prompt
    for rule in screen["suitability"]["rules"]:
        assert rule["rule_id"] in prompt
    for block in ("PLATFORM BRIEF", "SCREEN CONTEXT", "QUESTION"):
        assert block in prompt


def test_the_same_screen_and_data_give_a_byte_identical_prompt(login, model):
    advisor = login("advisor")
    ask(advisor, "Why?", portfolio_screen("C001"))
    ask(advisor, "Why?", portfolio_screen("C001"))
    first, second = model.requests
    assert first.user == second.user and first.system == second.system


def test_the_system_text_holds_the_scope_policy_and_the_read_only_rule(login, model):
    ask(login("advisor"), "Why?", portfolio_screen("C001"))
    system = model.requests[0].system.lower()
    assert "out of scope" in system and "investment advice" in system
    assert "read-only" in system
    assert "never state a figure" in system
    assert set(model.requests[0].schema["properties"]) == {
        "in_scope",
        "answer_markdown",
        "claims",
        "follow_up_questions",
    }


def test_the_prompt_carries_no_client_name_or_email_even_for_an_advisor_holding_client_pii(app, login, model):
    advisor = login("advisor")
    assert "client:pii" in advisor.get("/api/auth/me").json()["permissions"]
    with app.state.session_factory() as db:
        clients = db.scalars(select(ClientRow)).all()
    for c in clients[:5]:
        ask(advisor, "Tell me about this client", portfolio_screen(c.id))
    assert len(model.requests) == 5
    forbidden = {c.email for c in clients} | {c.name for c in clients} | {c.name.split()[-1] for c in clients}
    for request in model.requests:
        prompt = (request.system + "\n" + request.user).lower()
        assert not [f for f in forbidden if f.lower() in prompt]


@pytest.mark.parametrize("role", ["research_analyst", "investment_committee", "platform_owner"])
def test_a_portfolio_the_role_cannot_read_gets_the_refusal_and_reveals_nothing(login, model, role):
    c = login(role)
    real = ask(c, "What does this hold?", portfolio_screen("C001"))
    missing = ask(c, "What does this hold?", portfolio_screen("C999"))
    assert real.status_code == missing.status_code == 200
    a, b = real.json(), missing.json()
    assert a["outcome"] == b["outcome"] == "refused"
    assert a["answer"] == b["answer"] and a["answer"]["markdown"].startswith(REFUSAL_START)
    assert model.requests == []  # the model never sees an entity the user cannot read


def test_a_portfolio_that_does_not_exist_gets_the_same_refusal_for_a_reader(login, model):
    r = ask(login("advisor"), "What does this hold?", portfolio_screen("C999"))
    assert r.json()["outcome"] == "refused" and r.json()["answer"]["markdown"].startswith(REFUSAL_START)
    assert model.requests == []


def test_out_of_scope_from_the_model_returns_the_fixed_refusal_and_never_the_models_text(app, login, model):
    model.reply = answer("Buy NVDA now, it will double.", in_scope=False)
    turn = ask(login("advisor"), "Should I buy NVDA?", portfolio_screen("C001")).json()
    assert turn["outcome"] == "refused"
    assert turn["answer"]["markdown"].startswith(REFUSAL_START) and "NVDA" not in json.dumps(turn["answer"])
    (event,) = events(app, "assistant.refused")
    assert (event["exchange_id"], event["exchange_hash"]) == (turn["exchange_id"], turn["exchange_hash"])


def test_an_answered_turn_writes_an_audit_event_anchoring_its_exchange_and_the_chain_verifies(app, login, model):
    turn = ask(login("advisor"), "Why?", portfolio_screen("C001")).json()
    (event,) = events(app, "assistant.answered")
    assert (event["exchange_id"], event["exchange_hash"]) == (turn["exchange_id"], turn["exchange_hash"])
    assert event["seq"] == 1 and len(event["screen_context_hash"]) == 64
    auditor = login("auditor")
    ex = auditor.get(f"/api/llm/exchanges/{turn['exchange_id']}").json()
    assert ex["task"] == "assistant_answer" and ex["prompt_version"] == "assistant_answer@v1"
    verdict = auditor.get("/api/audit/verify").json()
    assert verdict["valid"] and verdict["exchanges_checked"] >= 1


def test_turns_in_one_login_share_a_conversation_and_are_numbered_in_order(app, login, model):
    advisor = login("advisor")
    seqs = [ask(advisor, f"Question {n}", portfolio_screen("C001")).json()["seq"] for n in range(3)]
    assert seqs == [1, 2, 3]
    conversations = {e["conversation_id"] for e in events(app, "assistant.answered")}
    assert len(conversations) == 1
    assert ask(login("advisor"), "Fresh login", portfolio_screen("C001")).json()["seq"] == 1


def test_a_reply_the_assistant_cannot_read_is_a_failed_turn_with_a_safe_message(app, login, model):
    model.reply = {"unexpected": "shape"}
    turn = ask(login("advisor"), "Why?", portfolio_screen("C001")).json()
    assert turn["outcome"] == "failed" and turn["answer"] is None
    (event,) = events(app, "assistant.failed")
    assert event["exchange_id"] == turn["exchange_id"]


def test_asking_without_assistant_use_is_403_and_audited(app, login, model, monkeypatch):
    from app import rbac

    monkeypatch.setitem(rbac.PERMISSIONS, "advisor", rbac.PERMISSIONS["advisor"] - {"assistant:use"})
    r = ask(login("advisor"), "Why?", portfolio_screen("C001"))
    assert r.status_code == 403
    assert any(e["permission"] == "assistant:use" for e in events(app, "access_denied"))
    assert model.requests == []


def test_asking_requires_a_login(client):
    assert ask(client, "Why?", portfolio_screen("C001")).status_code == 401


def test_an_out_of_scope_reply_that_leaves_the_other_fields_out_is_still_the_refusal(login, model):
    model.reply = {"in_scope": False}
    assert ask(login("advisor"), "Will rates fall?", portfolio_screen("C001")).json()["outcome"] == "refused"


def test_more_than_three_follow_up_questions_are_cut_to_three(login, model):
    model.reply = answer(follow_ups=["a?", "b?", "c?", "d?"])
    turn = ask(login("advisor"), "Why?", portfolio_screen("C001")).json()
    assert turn["outcome"] == "answered" and turn["answer"]["follow_up_questions"] == ["a?", "b?", "c?"]


def test_refusing_an_unreadable_portfolio_is_audited_without_an_exchange(app, login, model):
    ask(login("research_analyst"), "What does this hold?", portfolio_screen("C001"))
    (event,) = events(app, "assistant.refused")
    assert "exchange_id" not in event and event["screen_context_hash"] is None
    assert login("auditor").get("/api/audit/verify").json()["valid"]
