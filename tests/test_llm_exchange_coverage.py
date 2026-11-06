"""Seam: the HTTP API. Every AI step (Research Tilt, Recommendation memo, prioritisation narrative) is captured as an
LLM Exchange that its Audit Event references by id and hash, on success and on failure (ADR-0004). Prompts never carry
a client name or email, which is what lets `llm:read` stand apart from `client:pii`. Recordings and stubs; no network."""
import json
import re

import pytest
from sqlalchemy import select, text

from app import audit
from app.db import AuditEventRow, ClientRow
from app.exchanges import CapturingLlm
from tests.runs import run_and_wait
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


def step_events(app, *types):
    with app.state.session_factory() as db:
        rows = db.scalars(select(AuditEventRow).where(AuditEventRow.type.in_(types)).order_by(AuditEventRow.id)).all()
    return [(r.type, json.loads(r.payload_json)) for r in rows]


@pytest.fixture
def captured(app, ai):  # noqa: F811
    """The stubbed model, behind the same capture wrapper the app uses."""
    ai.approve("Information Technology", "equity")
    tilt_for(ai, equity=5.0)
    ai.stub.narrative = lambda payload: {"claims": []}
    ai.stub.priority_narrative = narrative_reply
    app.state.llm = CapturingLlm(ai.stub, app.state.session_factory, mode="recorded")
    return ai


def test_every_ai_step_is_captured_and_referenced_by_its_audit_event(app, login, captured):
    captured.run()
    auditor = login("auditor")
    seen = set()
    for event_type, payload in step_events(app, *STEPS):
        assert HEX64.match(payload.get("exchange_hash", "")), (event_type, payload)
        ex = auditor.get(f"/api/llm/exchanges/{payload['exchange_id']}").json()
        assert (ex["task"], ex["outcome"], ex["hash"]) == (STEPS[event_type], "ok", payload["exchange_hash"])
        seen.add(event_type)
    assert seen == set(STEPS)
    assert auditor.get("/api/audit/verify").json()["valid"]


def test_a_step_with_no_recording_is_captured_as_an_error_exchange_and_the_event_says_so(app, login, captured):
    app.state.llm = captured.stub.delegate  # the real recorded client: it has no recording for these steps
    captured.run()
    auditor = login("auditor")
    events = step_events(app, *STEPS)
    assert {t for t, _ in events} == set(STEPS)
    for event_type, payload in events:
        assert payload["status"] == "failed"
        ex = auditor.get(f"/api/llm/exchanges/{payload['exchange_id']}").json()
        assert (ex["task"], ex["outcome"], ex["hash"]) == (STEPS[event_type], "error", payload["exchange_hash"])
        assert "No recorded response" in ex["error"]
    assert auditor.get("/api/audit/verify").json()["valid"]


def test_a_reply_the_step_rejects_still_points_at_its_exchange(app, login, captured):
    captured.stub.tilt = lambda payload: {"unexpected": "shape"}
    captured.run()
    _, payload = step_events(app, "research_tilt_proposed")[0]
    assert payload["status"] == "failed"
    ex = login("auditor").get(f"/api/llm/exchanges/{payload['exchange_id']}").json()
    assert ex["outcome"] == "ok" and ex["hash"] == payload["exchange_hash"]  # the transport succeeded; the step refused


def test_losing_the_exchange_store_fails_each_ai_step_but_nothing_deterministic(app, login, captured):
    with app.state.session_factory() as db:
        db.execute(text("DROP TABLE llm_exchanges"))
        db.commit()
    advisor = captured.advisor
    run_and_wait(advisor)

    events = step_events(app, *STEPS)
    assert {t for t, _ in events} == set(STEPS)
    for _, payload in events:
        assert payload["status"] == "failed" and "exchange_id" not in payload
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
    exchange_ids = [p["exchange_id"] for _, p in step_events(app, *STEPS, "insight_extracted") if "exchange_id" in p]
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
