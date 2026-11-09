"""Self-correction against the guardrails (ADR-0010): an ungrounded first draft is told which Claims failed and why and
gets one retry; a draft exposing PII is rejected outright."""

import json

from sqlalchemy import select

from app.db import ClientRow
from app.seeder import PLANTED
from tests.scripted import ScriptedModel, serve
from tests.test_assistant import answer, ask, events, model, portfolio_screen  # noqa: F401 (imported fixtures)
from tests.test_portfolio import url
from tests.test_queue import seeded  # noqa: F401 (imported fixtures)

PORTFOLIO_ID = PLANTED["restricted_breach"]
RETRY_HINT = "Fix or remove"


def drift_reply(drift_pp):
    reply = answer(f"Portfolio Drift is {drift_pp} pp.")
    reply["claims"] = [
        {
            "text": f"Portfolio Drift is {drift_pp} pp.",
            "citations": [{"kind": "engine", "figure": "portfolio_drift_pp"}],
        }
    ]
    return reply


def actual_drift(advisor):
    return advisor.get(url(PORTFOLIO_ID)).json()["drift"]["portfolio_drift_pp"]


def test_an_ungrounded_draft_is_retried_once_with_its_issues_and_the_corrected_answer_is_grounded(app, login, model):
    advisor = login("advisor")
    script = serve(app, ScriptedModel(drift_reply(99), drift_reply(actual_drift(advisor))))
    turn = ask(advisor, "How far has it drifted?", portfolio_screen(PORTFOLIO_ID)).json()
    assert turn["outcome"] == "answered", turn
    assert len(script.requests) == 2
    (claim,) = turn["answer"]["claims"]
    assert claim["grounded"] is True
    retry = script.requests[1].user_prompt  # the retry feedback is the latest prompt
    assert "Portfolio Drift is 99 pp." in retry and "number_mismatch: 99 does not match" in retry
    steps = turn["trajectory"]["steps"]
    assert [s["kind"] for s in steps] == ["model_request", "self_correction", "model_request"]
    assert steps[1]["issue_count"] == 1
    (checked,) = events(app, "grounding_checked")  # only the final Answer's check is stored
    assert checked["check_id"] == turn["grounding_check_id"]
    assert events(app, "claim_ungrounded") == []
    event = events(app, "assistant.answered")[-1]
    assert len(event["exchanges"]) == 2
    auditor = login("auditor")
    exchange = auditor.get(f"/api/llm/exchanges/{turn['exchange_id']}").json()
    assert RETRY_HINT in json.dumps(exchange["messages"]) and "Portfolio Drift is 99 pp." in json.dumps(
        exchange["messages"]
    )
    assert auditor.get("/api/audit/verify").json()["valid"]


def test_a_draft_still_ungrounded_after_the_retry_is_kept_flagged_and_no_third_request_is_made(app, login, model):
    script = serve(app, ScriptedModel(drift_reply(99), drift_reply(98)))
    turn = ask(login("advisor"), "How far has it drifted?", portfolio_screen(PORTFOLIO_ID)).json()
    assert turn["outcome"] == "answered", turn
    assert len(script.requests) == 2
    (claim,) = turn["answer"]["claims"]
    assert claim["grounded"] is False and claim["text"] == "Portfolio Drift is 98 pp."
    assert [s["kind"] for s in turn["trajectory"]["steps"]] == ["model_request", "self_correction", "model_request"]
    (checked,) = events(app, "grounding_checked")
    assert checked["check_id"] == turn["grounding_check_id"]
    assert len(events(app, "claim_ungrounded")) == 1


def test_a_first_draft_exposing_pii_fails_the_turn_with_pii_after_exactly_one_request(app, login, model):
    with app.state.session_factory() as db:
        client = db.scalars(select(ClientRow)).first()
    reply = drift_reply(99)  # ungrounded too: PII is checked first and is never coached
    reply["answer_markdown"] = f"{client.name} drifts in equity."
    script = serve(app, ScriptedModel(reply))
    turn = ask(login("advisor"), "Why?", portfolio_screen(PORTFOLIO_ID)).json()
    assert turn["outcome"] == "failed" and turn["answer"] is None
    assert len(script.requests) == 1
    (event,) = events(app, "assistant.failed")
    assert event["reason"] == "pii" and len(event["exchanges"]) == 1
    assert events(app, "grounding_checked") == []
    assert [s["kind"] for s in turn["trajectory"]["steps"]] == ["model_request"]
