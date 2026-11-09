"""Seam: the HTTP API. Every AI step (Research Tilt, Recommendation memo, prioritisation narrative) is captured as an
LLM Exchange that its Audit Event references by id and hash, on success and on failure (ADR-0004). Prompts never carry
a client name or email, which is what lets `llm:read` stand apart from `client:pii`. Recordings and scripted Models; no
network."""

import json
import re
from collections import Counter

import pytest
from sqlalchemy import select, text

from app.db import AuditEventRow, ClientRow
from tests.runs import run_and_wait
from tests.scripted import serve
from tests.test_ai_recommendations import ai, tilt_for  # noqa: F401  (fixture)
from tests.test_portfolio import url
from tests.test_priority_narrative import narrative_reply
from tests.test_queue import seeded  # noqa: F401  (fixture)

STEPS = {  # audit event type -> exchange task name
    "research_tilt_proposed": "research_tilt",
    "memo_generated": "recommendation_narrative",
    "priority_narrative_generated": "priority_narrative",
}
HEX64 = re.compile(r"^[0-9a-f]{64}$")
PIPELINE_STEPS = {"insight_extracted": "insight_extraction", **STEPS}


def step_events(app, *types):
    with app.state.session_factory() as db:
        rows = db.scalars(select(AuditEventRow).where(AuditEventRow.type.in_(types)).order_by(AuditEventRow.id)).all()
    return [(r.type, json.loads(r.payload_json)) for r in rows]


@pytest.fixture
def captured(app, ai):  # noqa: F811
    """The stub Model, behind the same capture the app serves."""
    ai.approve("Information Technology", "equity")
    tilt_for(ai, equity=5.0)
    ai.stub.narrative = lambda payload: {"claims": []}
    ai.stub.priority_narrative = narrative_reply
    return ai


def test_every_ai_step_is_captured_and_referenced_by_its_audit_event(app, login, captured):
    captured.run()
    auditor = login("auditor")
    seen = set()
    events = step_events(app, *PIPELINE_STEPS)
    for event_type, payload in events:
        assert len(payload.get("exchanges") or []) == 1, (
            event_type,
            payload,
        )  # one Exchange, anchored as a list of one
        assert HEX64.match(payload["exchanges"][0]["exchange_hash"]), (event_type, payload)
        ex = auditor.get(f"/api/llm/exchanges/{payload['exchanges'][0]['exchange_id']}").json()
        assert (ex["task"], ex["outcome"], ex["hash"]) == (
            PIPELINE_STEPS[event_type],
            "ok",
            payload["exchanges"][0]["exchange_hash"],
        )
        seen.add(event_type)
    assert seen == set(PIPELINE_STEPS)
    for task, expected in Counter(PIPELINE_STEPS[event_type] for event_type, _ in events).items():
        exchanges = auditor.get("/api/llm/exchanges", params={"task": task}).json()
        assert exchanges["total"] == expected
    assert auditor.get("/api/audit/verify").json()["valid"]


def test_a_step_with_no_recording_is_captured_as_an_error_exchange_and_the_event_says_so(app, login, captured):
    serve(app, captured.replay)  # the app's own replay Model: it has no recording for these steps
    captured.run()
    auditor = login("auditor")
    events = step_events(app, *STEPS)
    assert {t for t, _ in events} == set(STEPS)
    for event_type, payload in events:
        assert payload["status"] == "failed"
        ex = auditor.get(f"/api/llm/exchanges/{payload['exchanges'][0]['exchange_id']}").json()
        assert (ex["task"], ex["outcome"], ex["hash"]) == (
            STEPS[event_type],
            "error",
            payload["exchanges"][0]["exchange_hash"],
        )
        assert "No recorded response" in ex["error"]
    assert auditor.get("/api/audit/verify").json()["valid"]


def test_a_reply_the_step_rejects_still_points_at_its_exchange(app, login, captured):
    captured.stub.tilt = lambda payload: {"unexpected": "shape"}
    captured.run()
    _, payload = step_events(app, "research_tilt_proposed")[0]
    assert payload["status"] == "failed"
    ex = login("auditor").get(f"/api/llm/exchanges/{payload['exchanges'][0]['exchange_id']}").json()
    assert (
        ex["outcome"] == "ok" and ex["hash"] == payload["exchanges"][0]["exchange_hash"]
    )  # the transport succeeded; the step refused


def test_losing_the_exchange_store_fails_each_ai_step_but_nothing_deterministic(app, login, captured):
    with app.state.session_factory() as db:
        db.execute(text("DROP TABLE llm_exchanges"))
        db.commit()
    advisor = captured.advisor
    run_and_wait(advisor)

    events = step_events(app, *STEPS)
    assert {t for t, _ in events} == set(STEPS)
    for _, payload in events:
        assert payload["status"] == "failed" and "exchanges" not in payload
    queue = advisor.get("/api/queue").json()["items"]
    assert queue and all(i["score"] is not None for i in queue)
    rec = advisor.get(url("C003")).json()["recommendation"]
    assert rec["trade_lines"] and rec["suitability"]
    assert rec["research"]["tilt"]["status"] == "failed"
    decided = advisor.post(f"/api/recommendations/{rec['id']}/decision", json={"action": "accept"})
    assert decided.status_code == 200, decided.text
    # events written before the store was lost still pin Exchanges that are now gone; verification says so rather than erroring
    verdict = login("auditor").get("/api/audit/verify").json()
    assert verdict["valid"] is False and "missing" in verdict["reason"]
    assert verdict["first_broken_exchange_id"] is not None


def test_no_client_name_or_email_ever_appears_in_a_captured_prompt(app, login, captured):
    captured.run()
    auditor = login("auditor")
    exchange_ids = [
        p["exchanges"][0]["exchange_id"] for _, p in step_events(app, *STEPS, "insight_extracted") if "exchanges" in p
    ]
    assert len(set(exchange_ids)) >= 4  # extraction, tilts, memos and narratives for the seeded clients
    with app.state.session_factory() as db:
        clients = db.scalars(select(ClientRow)).all()
    assert len(clients) > 10
    forbidden = {c.email for c in clients} | {c.name for c in clients} | {c.name.split()[-1] for c in clients}
    for exchange_id in exchange_ids:
        ex = auditor.get(f"/api/llm/exchanges/{exchange_id}").json()
        prompt = ex["system_text"] + "\n" + ex["user_prompt"]
        leaked = [f for f in forbidden if f.lower() in prompt.lower()]
        assert not leaked, (ex["task"], leaked)


def test_a_run_started_from_the_cli_captures_every_ai_step_as_an_exchange_too(app, settings, seeded, login):
    """`python -m app.analysis` must not be a way round capture: on the committed recordings its AI steps succeed, and
    every one of them is an Exchange the Auditor can open, anchored in the chain."""
    from app import analysis
    from app.research_seed import seed_research

    seed_research(app.state.session_factory, settings.seed_dir)
    analysis.main(settings)
    auditor = login("auditor")
    events = step_events(app, *STEPS)
    assert events, "the run made no AI step"
    assert all(
        HEX64.match((payload.get("exchanges") or [{}])[0].get("exchange_hash") or "") for _, payload in events
    ), events[:1]
    verified = auditor.get("/api/audit/verify").json()
    assert verified["valid"] and verified["exchanges_checked"] == len(events)
