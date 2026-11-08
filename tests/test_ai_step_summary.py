"""Seam: the HTTP API. A Recommendation's AI contribution carries a per-step summary (mode, latency, grounded counts,
outcome) for any role that can read it, with no raw text; only `llm:read` roles also get the Exchange id (ADR-0004)."""

import json

import pytest

from app.exchanges import CapturingLlm
from tests.test_ai_recommendations import ai, tilt_for  # noqa: F401  (fixture)
from tests.test_portfolio import url
from tests.test_queue import seeded  # noqa: F401  (fixture)


@pytest.fixture
def captured(app, ai):  # noqa: F811
    ai.approve("Information Technology", "equity")
    tilt_for(ai, equity=5.0)
    ai.stub.narrative = lambda payload: {"claims": []}
    app.state.llm = CapturingLlm(ai.stub, app.state.session_factory, mode="recorded")
    return ai


def steps(rec):
    return {s["step"]: s for s in rec["research"]["steps"]}


def test_an_advisor_sees_each_ai_step_with_mode_outcome_and_counts_but_no_raw_text_or_exchange_id(captured):
    rec = captured.run()
    got = steps(rec)
    assert set(got) == {"tilt", "memo"}
    assert got["tilt"]["mode"] == "recorded" and got["tilt"]["outcome"] == "ok"
    assert got["memo"]["grounded"] == 0 and got["memo"]["ungrounded"] == 0
    assert got["tilt"]["latency_ms"] is None and got["tilt"]["telemetry"] == "not_available_replayed"
    blob = json.dumps(rec["research"]["steps"])
    for forbidden in ("exchange_hash", "system_text", "user_prompt", "raw_reply"):
        assert forbidden not in blob
    assert all(s["exchange_id"] is None for s in got.values())


@pytest.mark.parametrize("role", ["advisor", "relationship_manager"])
def test_client_facing_roles_get_the_same_summary_and_never_an_exchange_id(captured, login, role):
    captured.run()
    rec = (
        login(role)
        .get(f"/api/recommendations/{captured.advisor.get(url('C003')).json()['recommendation']['id']}")
        .json()
    )
    assert set(steps(rec)) == {"tilt", "memo"}
    assert all(s["exchange_id"] is None for s in steps(rec).values())


def test_a_role_with_llm_read_also_gets_the_exchange_id_that_opens_the_exchange(app, captured, login):
    rec = captured.run()
    auditor_view = login("auditor").get(f"/api/recommendations/{rec['id']}").json()
    for s in steps(auditor_view).values():
        ex = login("auditor").get(f"/api/llm/exchanges/{s['exchange_id']}")
        assert ex.status_code == 200 and ex.json()["mode"] == s["mode"]


def test_a_failed_step_shows_failed_with_its_transport_error_and_the_rule_based_result_stands(app, captured):
    app.state.llm = captured.stub.delegate  # the app's own replay path, which has no tilt or memo recordings
    rec = captured.run()
    got = steps(rec)
    assert {s["outcome"] for s in got.values()} == {"failed"}
    assert "No recorded response" in got["tilt"]["reason"] and len(got["memo"]["reason"]) <= 200
    assert got["memo"]["grounded"] is None
    assert rec["trade_lines"] and rec["research"]["tilt"]["status"] == "failed"


def test_a_plain_rule_based_recommendation_has_no_ai_contribution_and_so_no_steps(ai):
    rec = ai.run()  # no Insight approved: nothing for the model to work from
    assert rec["research"] is None
