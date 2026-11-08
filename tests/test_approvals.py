"""Seam: the tiered approval lifecycle through the HTTP API.

Advisor always; Compliance only when a rule is in breach; Investment Committee only when high-impact
(turnover >= 15% of the Portfolio or any Trade Line >= 10%, from config). C003 (cash drag) is high-impact by default
(turnover ~25%, SGOV sell ~25%) and clean on suitability; the breaching modification (all SGOV into XLK) is both.
"""

import json

import pytest
from sqlalchemy import select

from app import audit
from app.db import AuditEventRow
from tests.runs import run_and_wait
from tests.test_portfolio import url
from tests.test_queue import seeded  # noqa: F401  (fixture)
from tests.test_recommendations import breaching_lines, decide, rec

NEVER = {"approval_thresholds": {"turnover_pct": 100, "trade_line_pct": 100}}  # nothing is high-impact


@pytest.fixture
def advisor(login, seeded):  # noqa: F811
    c = login("advisor")
    run_and_wait(c)
    return c


@pytest.fixture
def compliance(login):
    return login("compliance_officer")


@pytest.fixture
def committee(login):
    return login("investment_committee")


def set_config(login, body):
    assert login("platform_owner").patch("/api/config", json=body).status_code == 200


def act(c, step, rec_id, action, rationale=None):
    return c.post(f"/api/recommendations/{rec_id}/{step}", json={"action": action, "rationale": rationale})


def status(c, cid="C003"):
    return rec(c, cid)["status"]


def breach_pending(advisor):
    """C003 modified into a Suitability breach and accepted by the Advisor."""
    v1 = rec(advisor, "C003")
    v2 = decide(advisor, v1["id"], "modify", "More growth", breaching_lines(advisor, "C003")).json()["recommendation"]
    assert decide(advisor, v2["id"], "accept").status_code == 200
    return v2["id"]


def test_high_impact_clean_recommendation_goes_to_committee_only(advisor, committee):
    r = rec(advisor, "C003")
    assert r["approval"]["needs_compliance"] is False and r["approval"]["high_impact"] is True
    assert r["approval"]["required_steps"] == ["advisor", "committee"]
    assert decide(advisor, r["id"], "accept").json()["recommendation"]["status"] == "pending_committee"
    out = act(committee, "committee", r["id"], "approve", "Large but within mandate")
    assert out.status_code == 200, out.text
    assert out.json()["recommendation"]["status"] == "approved"
    assert out.json()["decision"]["action"] == "committee_approve"
    assert status(advisor) == "approved"


def test_committee_can_reject_with_rationale(advisor, committee):
    r = rec(advisor, "C003")
    decide(advisor, r["id"], "accept")
    assert (
        act(committee, "committee", r["id"], "reject", "Too much turnover").json()["recommendation"]["status"]
        == "rejected"
    )


def test_breach_without_high_impact_needs_compliance_only(advisor, compliance, login):
    set_config(login, NEVER)
    r_id = breach_pending(advisor)
    assert status(advisor) == "pending_compliance"
    assert rec(advisor, "C003")["approval"]["required_steps"] == ["advisor", "compliance"]
    out = act(compliance, "compliance", r_id, "approve", "Client signed a waiver")
    assert out.status_code == 200, out.text
    assert out.json()["recommendation"]["status"] == "approved"
    assert out.json()["decision"]["action"] == "approve_exception"


def test_breach_and_high_impact_needs_both_in_order(advisor, compliance, committee):
    r_id = breach_pending(advisor)
    assert rec(advisor, "C003")["approval"]["required_steps"] == ["advisor", "compliance", "committee"]
    assert act(committee, "committee", r_id, "approve", "early").status_code == 409  # not before Compliance
    assert (
        act(compliance, "compliance", r_id, "approve", "Waiver on file").json()["recommendation"]["status"]
        == "pending_committee"
    )
    assert act(compliance, "compliance", r_id, "approve", "again").status_code == 409  # already past Compliance
    assert act(committee, "committee", r_id, "approve", "Agreed").json()["recommendation"]["status"] == "approved"


def test_compliance_can_block(advisor, compliance, login):
    set_config(login, NEVER)
    r_id = breach_pending(advisor)
    out = act(compliance, "compliance", r_id, "block", "Not suitable for a conservative Client")
    assert out.json()["recommendation"]["status"] == "rejected" and out.json()["decision"]["action"] == "block"
    assert act(compliance, "compliance", r_id, "approve", "changed my mind").status_code == 409


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_compliance_and_committee_decisions_require_a_rationale(advisor, compliance, committee, login, blank):
    r_id = breach_pending(advisor)
    for action in ("approve", "block"):
        assert act(compliance, "compliance", r_id, action, blank).status_code == 422
    assert status(advisor) == "pending_compliance"
    act(compliance, "compliance", r_id, "approve", "ok")
    for action in ("approve", "reject"):
        assert act(committee, "committee", r_id, action, blank).status_code == 422
    assert status(advisor) == "pending_committee"


def test_compliance_cannot_act_before_the_advisor_has_decided(advisor, compliance):
    v1 = rec(advisor, "C003")
    assert v1["status"] == "pending_advisor"
    for action in ("approve", "block"):
        assert act(compliance, "compliance", v1["id"], action, "why").status_code == 409
    assert status(advisor) == "pending_advisor"


def test_no_path_reaches_approved_without_a_human_decision_at_every_required_step(
    advisor, compliance, committee, login
):
    """Invariant: from each state, every out-of-order or wrong-role attempt fails and the status never reaches approved."""
    attempts = [
        (c, step, a)
        for c in (advisor, compliance, committee)
        for step in ("compliance", "committee")
        for a in ("approve", "block", "reject")
    ]
    r_id = breach_pending(advisor)  # pending_compliance, both steps required
    seen = ["pending_compliance"]
    for c, step, a in attempts:
        if (c is compliance and step == "compliance") and a in ("approve", "block"):
            continue  # the one legitimate move
        out = act(c, step, r_id, a, "forcing it")
        assert out.status_code in (403, 409, 422), (step, a, out.text)
    assert status(advisor) == "pending_compliance"
    # the advisor decision endpoint cannot be used to skip ahead either
    assert decide(advisor, r_id, "accept").status_code == 409
    act(compliance, "compliance", r_id, "approve", "ok")
    seen.append(status(advisor))
    for c, step, a in attempts:
        if c is committee and step == "committee" and a in ("approve", "reject"):
            continue
        assert act(c, step, r_id, a, "forcing it").status_code in (403, 409, 422), (step, a)
    assert decide(advisor, r_id, "accept").status_code == 409
    assert seen == ["pending_compliance", "pending_committee"] and status(advisor) == "pending_committee"
    act(committee, "committee", r_id, "approve", "ok")
    assert status(advisor) == "approved"


def test_a_clean_in_threshold_recommendation_is_approved_by_the_advisor_alone(advisor, login):
    set_config(login, {"approval_thresholds": {"turnover_pct": 30, "trade_line_pct": 30}})
    r = rec(advisor, "C003")
    assert r["approval"]["required_steps"] == ["advisor"]
    assert decide(advisor, r["id"], "accept").json()["recommendation"]["status"] == "approved"


@pytest.mark.parametrize(
    "thresholds,high",
    [
        ({"turnover_pct": 25.5, "trade_line_pct": 30}, False),
        ({"turnover_pct": 20, "trade_line_pct": 30}, True),  # turnover alone
        ({"turnover_pct": 100, "trade_line_pct": 20}, True),  # one Trade Line alone (SGOV ~25%)
        ({"turnover_pct": 100, "trade_line_pct": 26}, False),
    ],
)
def test_thresholds_are_read_from_config(advisor, login, thresholds, high):
    set_config(login, {"approval_thresholds": thresholds})
    a = rec(advisor, "C003")["approval"]
    assert a["high_impact"] is high and a["thresholds"] == thresholds
    assert bool(a["reasons"]) is high


def test_superseded_recommendations_cannot_be_decided_at_any_step(advisor, compliance, committee, login):
    r_id = breach_pending(advisor)
    run_and_wait(advisor)  # supersedes the pending one
    assert act(compliance, "compliance", r_id, "approve", "ok").status_code == 409
    assert act(committee, "committee", r_id, "approve", "ok").status_code == 409
    assert decide(advisor, r_id, "accept").status_code == 409
    assert advisor.get(f"/api/recommendations/{r_id}").json()["status"] == "superseded"


def test_a_run_supersedes_recommendations_waiting_on_the_committee(advisor, committee):
    r = rec(advisor, "C003")
    decide(advisor, r["id"], "accept")
    assert status(advisor) == "pending_committee"
    run_and_wait(advisor)
    assert act(committee, "committee", r["id"], "approve", "late").status_code == 409
    assert advisor.get(f"/api/recommendations/{r['id']}").json()["status"] == "superseded"


@pytest.mark.parametrize(
    "role,step,ok",
    [
        ("advisor", "compliance", False),
        ("relationship_manager", "committee", False),
        ("auditor", "compliance", False),
        ("investment_committee", "compliance", False),
        ("compliance_officer", "committee", False),
        ("platform_owner", "committee", False),
    ],
)
def test_only_the_right_role_may_take_each_step(login, advisor, role, step, ok):
    r_id = breach_pending(advisor)
    out = act(login(role), step, r_id, "approve", "because")
    assert out.status_code == 403 and status(advisor) == "pending_compliance"


def test_approvals_are_audited_with_rationale_and_lineage(advisor, compliance, committee, app):
    r_id = breach_pending(advisor)
    act(compliance, "compliance", r_id, "approve", "Waiver on file")
    act(committee, "committee", r_id, "approve", "Agreed")
    with app.state.session_factory() as db:
        evs = [
            e for e in db.scalars(select(AuditEventRow).order_by(AuditEventRow.id)) if e.recommendation_id == str(r_id)
        ]
        by_type = lambda t: [e for e in evs if e.type == t]  # noqa: E731
        parents = lambda e: json.loads(e.parent_ids_json)  # noqa: E731
        accepted = [e for e in by_type("decision_recorded") if json.loads(e.payload_json)["action"] == "accept"][0]
        (exc,) = by_type("exception_approved")
        assert (exc.actor_name, exc.actor_role) == ("compliance_officer", "compliance_officer")
        assert json.loads(exc.payload_json)["rationale"] == "Waiver on file" and accepted.id in parents(exc)
        final = [
            e for e in by_type("decision_recorded") if json.loads(e.payload_json)["action"] == "committee_approve"
        ][0]
        assert (final.actor_role, json.loads(final.payload_json)["rationale"]) == ("investment_committee", "Agreed")
        assert exc.id in parents(final) and json.loads(final.payload_json)["resulting_status"] == "approved"
        assert audit.verify(db).valid


def test_blocked_exception_is_audited(advisor, compliance, login, app):
    set_config(login, NEVER)
    r_id = breach_pending(advisor)
    act(compliance, "compliance", r_id, "block", "Unsuitable")
    with app.state.session_factory() as db:
        (ev,) = [e for e in db.scalars(select(AuditEventRow).where(AuditEventRow.type == "exception_blocked"))]
        assert json.loads(ev.payload_json)["rationale"] == "Unsuitable" and ev.recommendation_id == str(r_id)


def test_decisions_appear_in_the_portfolio_history(advisor, compliance, login):
    set_config(login, NEVER)
    r_id = breach_pending(advisor)
    act(compliance, "compliance", r_id, "approve", "Waiver")
    ds = advisor.get(url("C003")).json()["history"]["decisions"]
    assert [(d["action"], d["actor_role"]) for d in ds if d["recommendation_id"] == r_id] == [
        ("accept", "advisor"),
        ("approve_exception", "compliance_officer"),
    ]


def test_compliance_view_shows_rule_limit_actual_affected_lines_and_restrictions(advisor, compliance, app):
    from app.db import RestrictionRow

    with app.state.session_factory() as db:
        db.add(RestrictionRow(client_id="C003", kind="sector", value="Energy"))
        db.commit()
    r_id = breach_pending(advisor)
    items = compliance.get("/api/approvals").json()["items"]
    assert [i["recommendation"]["id"] for i in items] == [r_id] and items[0]["step"] == "compliance"
    item = items[0]
    sr01 = next(r for r in item["rules"] if r["rule_id"] == "SR-01")
    f = sr01["findings"][0]
    assert sr01["status"] == "breach" and f["limit"] == 30 and f["actual"] > 30 and f["subject"] == "equity"
    assert "XLK" in [line["symbol"] for line in f["affected_trade_lines"]]
    assert all(r["status"] != "pass" for r in item["rules"])  # breaches and warnings, not passes
    assert {"kind": "sector", "value": "Energy"} in item["restrictions"]
    assert item["portfolio_id"] == "C003" and item["client_name"]  # compliance sees names (client:pii)


def test_committee_panel_lists_only_pending_committee_with_thresholds(advisor, committee, compliance):
    assert committee.get("/api/approvals").json()["items"] == []
    r = rec(advisor, "C003")
    decide(advisor, r["id"], "accept")
    items = committee.get("/api/approvals").json()["items"]
    assert [(i["recommendation"]["id"], i["step"]) for i in items] == [(r["id"], "committee")]
    assert items[0]["recommendation"]["approval"]["thresholds"] == {"turnover_pct": 15.0, "trade_line_pct": 10.0}
    assert items[0]["recommendation"]["approval"]["reasons"]
    assert compliance.get("/api/approvals").json()["items"] == []  # nothing waits on Compliance


def test_approvals_panel_is_for_compliance_and_committee_only(login, advisor):
    for role, ok in [
        ("compliance_officer", True),
        ("investment_committee", True),
        ("advisor", False),
        ("auditor", False),
        ("platform_owner", False),
        ("relationship_manager", False),
    ]:
        assert (login(role).get("/api/approvals").status_code == 200) is ok


def test_unknown_recommendation_is_404_on_both_steps(compliance, committee, advisor):
    assert act(compliance, "compliance", 99999, "approve", "x").status_code == 404
    assert act(committee, "committee", 99999, "approve", "x").status_code == 404


def test_invalid_action_is_rejected(compliance, advisor):
    r_id = breach_pending(advisor)
    assert act(compliance, "compliance", r_id, "reject", "x").status_code == 422


def test_raising_thresholds_while_waiting_on_the_committee_does_not_break_the_decision(advisor, committee, login):
    r = rec(advisor, "C003")
    decide(advisor, r["id"], "accept")
    assert status(advisor) == "pending_committee"
    set_config(login, NEVER)  # no longer high-impact, but it already waits on the Committee
    out = act(committee, "committee", r["id"], "approve", "Still needs my sign-off")
    assert out.status_code == 200 and out.json()["recommendation"]["status"] == "approved"


def test_findings_on_measures_name_the_trade_lines_that_drive_them(advisor, compliance):
    breach_pending(advisor)
    item = compliance.get("/api/approvals").json()["items"][0]
    by_subject = {f["subject"]: f for r in item["rules"] for f in r["findings"]}
    assert {line["symbol"] for line in by_subject["equity"]["affected_trade_lines"]} >= {"XLK"}


def test_lowering_thresholds_before_the_committee_step_adds_it(advisor, compliance, login):
    set_config(login, NEVER)
    r_id = breach_pending(advisor)  # needs Compliance only while nothing is high-impact
    assert rec(advisor, "C003")["approval"]["required_steps"] == ["advisor", "compliance"]
    set_config(login, {"approval_thresholds": {"turnover_pct": 15, "trade_line_pct": 10}})
    out = act(compliance, "compliance", r_id, "approve", "Exception accepted")
    assert out.status_code == 200 and out.json()["recommendation"]["status"] == "pending_committee"
