"""Seam: band-based Recommendations and the Advisor's Decisions through the HTTP API against planted scenarios.

Expected numbers are the planted weights in app/seeder.py (whole-unit quantities, hence the tolerances).
C003 (conservative): cash 40% vs 15% target, bonds 40% vs 65%  -> sell SGOV ~25%, buy AGG ~15.6% and SHY ~9.4%.
C002 (moderate): equity 60% vs 45%, bonds 35% vs 45%, cash 5% vs 10%.
"""
import json

import pytest
from sqlalchemy import select

from app import audit
from app.db import AuditEventRow
from app.seeder import PLANTED
from tests.test_portfolio import url
from tests.test_queue import QUEUE, seeded  # noqa: F401  (fixture)


@pytest.fixture
def advisor(login, seeded):  # noqa: F811
    c = login("advisor")
    assert c.post("/api/analysis/runs").status_code == 200
    return c


def rec(c, cid):
    return c.get(url(cid)).json()["recommendation"]


def decide(c, rec_id, action, rationale=None, trade_lines=None):
    body = {"action": action, "rationale": rationale}
    if trade_lines is not None:
        body["trade_lines"] = trade_lines
    return c.post(f"/api/recommendations/{rec_id}/decision", json=body)


def lines_by(r, side):
    return {(l["symbol"]): l for l in r["trade_lines"] if l["side"] == side}


# A modification that pushes a conservative Client to 30%+ equity: sell all SGOV, buy XLK.
def breaching_lines(c, cid):
    held = {h["symbol"]: h for h in c.get(url(cid)).json()["holdings"]}
    sgov = held["SGOV"]
    return [
        {"account_id": sgov["account_id"], "symbol": "SGOV", "side": "sell", "quantity": sgov["quantity"]},
        {"account_id": sgov["account_id"], "symbol": "XLK", "side": "buy", "quantity": int(sgov["market_value"] // 100)},
    ]


def test_clean_portfolio_and_in_band_portfolios_get_no_recommendation(advisor):
    for key in ("clean", "heavy_tech", "restricted_breach"):  # the last two have no Asset-Class Drift
        body = advisor.get(url(PLANTED[key])).json()
        assert body["recommendation"] is None, key
        assert body["history"] == {"versions": [], "decisions": []}


def test_no_recommendation_before_any_run(login, seeded):  # noqa: F811
    assert login("advisor").get(url("C003")).json()["recommendation"] is None


def test_cash_drag_scenario_yields_expected_trade_lines(advisor):
    r = rec(advisor, PLANTED["cash_drag"])
    assert r["version"] == 1 and r["parent_id"] is None and r["status"] == "pending_advisor"
    sells, buys = lines_by(r, "sell"), lines_by(r, "buy")
    assert set(sells) == {"SGOV"} and set(buys) == {"AGG", "SHY"}
    assert sells["SGOV"]["pct_of_portfolio"] == pytest.approx(25, abs=0.3)
    assert buys["AGG"]["pct_of_portfolio"] == pytest.approx(15.6, abs=0.3)
    assert buys["SHY"]["pct_of_portfolio"] == pytest.approx(9.4, abs=0.3)
    assert r["turnover_pct"] == pytest.approx(25, abs=0.3)
    for l in r["trade_lines"]:  # percent and currency both present and consistent
        assert l["amount"] == pytest.approx(l["quantity"] * l["price"], abs=0.01)
        assert l["pct_of_portfolio"] == pytest.approx(l["amount"] / r["total_value"] * 100, abs=0.01)
        assert l["currency"] == "USD" and l["quantity"] > 0


def test_energy_overweight_scenario_yields_expected_trade_lines(advisor):
    r = rec(advisor, PLANTED["overweight_energy"])
    sells, buys = lines_by(r, "sell"), lines_by(r, "buy")
    assert set(sells) == {"XOM", "XLE", "SPY", "JNJ", "PG"}  # equity sold pro rata
    assert sells["XOM"]["pct_of_portfolio"] == pytest.approx(3.75, abs=0.3)
    assert sells["JNJ"]["pct_of_portfolio"] == pytest.approx(2.5, abs=0.3)
    assert sells["PG"]["pct_of_portfolio"] == pytest.approx(1.25, abs=0.3)
    assert set(buys) == {"AGG", "LQD", "SHY", "SGOV"}
    assert buys["AGG"]["pct_of_portfolio"] == pytest.approx(4.29, abs=0.3)
    assert buys["SGOV"]["pct_of_portfolio"] == pytest.approx(5, abs=0.3)
    assert r["turnover_pct"] == pytest.approx(15, abs=0.3)


def test_never_sells_more_than_held_and_returns_portfolio_to_target(advisor):
    p = advisor.get(url(PLANTED["overweight_energy"])).json()
    held = {(h["account_id"], h["symbol"]): h["quantity"] for h in p["holdings"]}
    for l in p["recommendation"]["trade_lines"]:
        if l["side"] == "sell":
            assert l["quantity"] <= held[(l["account_id"], l["symbol"])]
    assert all(c["drift_pp"] < 0.5 for c in p["recommendation"]["post_trade_drift"])


def test_recommendation_carries_post_trade_suitability_and_engine_summary(advisor):
    r = rec(advisor, PLANTED["overweight_energy"])
    assert [x["rule_id"] for x in r["suitability"]["rules"]] == [f"SR-0{n}" for n in range(1, 8)]
    assert r["suitability"]["status"] in ("pass", "warning", "breach")
    assert "equity" in r["summary"].lower() and r["created_by"]


def test_accept_without_breach_is_approved_but_executes_nothing(advisor):
    r = rec(advisor, PLANTED["cash_drag"])
    assert r["suitability"]["status"] != "breach"
    out = decide(advisor, r["id"], "accept")
    assert out.status_code == 200, out.text
    body = out.json()
    assert body["recommendation"]["status"] == "approved" and body["recommendation"]["id"] == r["id"]
    assert body["decision"]["action"] == "accept" and body["decision"]["actor_name"] == "advisor"
    assert rec(advisor, PLANTED["cash_drag"])["status"] == "approved"


def test_reject_and_modify_require_a_rationale_but_accept_does_not(advisor):
    r = rec(advisor, PLANTED["cash_drag"])
    for blank in (None, "", "   "):
        assert decide(advisor, r["id"], "reject", blank).status_code == 422
        assert decide(advisor, r["id"], "modify", blank, breaching_lines(advisor, "C003")).status_code == 422
    assert rec(advisor, "C003")["status"] == "pending_advisor"  # nothing changed
    assert decide(advisor, r["id"], "reject", "Client prefers to hold cash").status_code == 200
    assert rec(advisor, "C003")["status"] == "rejected"


def test_modification_creates_a_linked_version_and_surfaces_new_breaches(advisor):
    v1 = rec(advisor, "C003")
    assert v1["suitability"]["status"] != "breach"
    out = decide(advisor, v1["id"], "modify", "Client wants more growth", breaching_lines(advisor, "C003"))
    assert out.status_code == 200, out.text
    body = out.json()
    v2 = body["recommendation"]
    assert v2["id"] != v1["id"] and v2["version"] == 2 and v2["parent_id"] == v1["id"]
    assert v2["status"] == "pending_advisor"
    assert v2["suitability"]["status"] == "breach"  # re-run immediately
    assert "SR-01" in [x["rule_id"] for x in body["new_breaches"]]
    assert body["decision"]["action"] == "modify" and body["decision"]["resulting_recommendation_id"] == v2["id"]
    current = rec(advisor, "C003")
    assert current["id"] == v2["id"]
    versions = advisor.get(url("C003")).json()["history"]["versions"]
    assert [(v["version"], v["status"]) for v in versions] == [(1, "superseded"), (2, "pending_advisor")]


def test_accepting_a_version_in_breach_is_not_approved(advisor):
    v1 = rec(advisor, "C003")
    v2 = decide(advisor, v1["id"], "modify", "More growth", breaching_lines(advisor, "C003")).json()["recommendation"]
    out = decide(advisor, v2["id"], "accept").json()
    assert out["recommendation"]["status"] == "pending_compliance"  # compliance sign-off arrives in ticket 08
    assert out["recommendation"]["status"] != "approved"


def test_decisions_on_non_pending_versions_are_rejected(advisor):
    v1 = rec(advisor, "C003")
    decide(advisor, v1["id"], "modify", "More growth", breaching_lines(advisor, "C003"))
    assert decide(advisor, v1["id"], "accept").status_code == 409  # superseded
    v2 = rec(advisor, "C003")
    assert decide(advisor, v2["id"], "reject", "no").status_code == 200
    assert decide(advisor, v2["id"], "accept").status_code == 409  # already decided


@pytest.mark.parametrize("mutate,msg", [
    (lambda ls, h: ls[0].update(quantity=h["quantity"] + 1), "more than held"),
    (lambda ls, h: ls[0].update(symbol="NOPE"), "unknown"),
    (lambda ls, h: ls[0].update(quantity=0), "positive"),
    (lambda ls, h: ls[0].update(account_id="C999-TX"), "account"),
    (lambda ls, h: ls.append(dict(ls[0])), "duplicate"),
    (lambda ls, h: ls.clear(), "at least one"),
])
def test_invalid_modifications_are_rejected_and_change_nothing(advisor, mutate, msg):
    v1 = rec(advisor, "C003")
    held = next(h for h in advisor.get(url("C003")).json()["holdings"] if h["symbol"] == "SGOV")
    lines = breaching_lines(advisor, "C003")
    mutate(lines, held)
    out = decide(advisor, v1["id"], "modify", "Because", lines)
    assert out.status_code == 422 and msg in out.text.lower()
    assert rec(advisor, "C003")["id"] == v1["id"] and rec(advisor, "C003")["status"] == "pending_advisor"


def test_modify_requires_trade_lines(advisor):
    v1 = rec(advisor, "C003")
    assert decide(advisor, v1["id"], "modify", "Because").status_code == 422


def test_decisions_are_audited_with_rationale_and_lineage(advisor, app):
    v1 = rec(advisor, "C003")
    v2 = decide(advisor, v1["id"], "modify", "More growth", breaching_lines(advisor, "C003")).json()["recommendation"]
    decide(advisor, v2["id"], "reject", "Too risky")
    with app.state.session_factory() as db:
        evs = list(db.scalars(select(AuditEventRow).where(AuditEventRow.client_id == "C003").order_by(AuditEventRow.id)))
        by_id = {e.id: e for e in evs}
        parents = lambda e: json.loads(e.parent_ids_json)  # noqa: E731
        of = lambda t, rid: [e for e in evs if e.type == t and e.recommendation_id == str(rid)]  # noqa: E731

        drafted = of("recommendation_drafted", v1["id"])[0]
        assert drafted.actor_kind == "system"
        started = next(e for e in db.scalars(select(AuditEventRow)) if e.type == "analysis_run_started")
        assert started.id in parents(drafted)
        assert of("suitability_evaluated", v1["id"])  # post-trade results audited

        d1 = of("decision_recorded", v1["id"])[0]
        assert of("suitability_evaluated", v1["id"])[0].id in parents(d1)  # chained after the draft's own results
        p1 = json.loads(d1.payload_json)
        assert (p1["action"], p1["rationale"], d1.actor_name, d1.actor_role) == ("modify", "More growth", "advisor", "advisor")

        modified = of("recommendation_modified", v2["id"])[0]
        assert d1.id in parents(modified)
        pm = json.loads(modified.payload_json)
        assert pm["parent_recommendation_id"] == v1["id"] and pm["version"] == 2 and pm["trade_lines"]
        sv = of("suitability_evaluated", v2["id"])[0]
        assert modified.id in parents(sv) and json.loads(sv.payload_json)["status"] == "breach"

        d2 = of("decision_recorded", v2["id"])[0]
        assert json.loads(d2.payload_json)["action"] == "reject" and sv.id in parents(d2)
        assert by_id[d2.id].recommendation_id == str(v2["id"])
        assert audit.verify(db).valid


def test_decision_history_is_listed_on_the_drill_down(advisor):
    v1 = rec(advisor, "C003")
    decide(advisor, v1["id"], "modify", "More growth", breaching_lines(advisor, "C003"))
    ds = advisor.get(url("C003")).json()["history"]["decisions"]
    assert [(d["action"], d["rationale"], d["recommendation_id"]) for d in ds] == [("modify", "More growth", v1["id"])]
    assert ds[0]["created_at"] and ds[0]["actor_role"] == "advisor"


def test_new_run_supersedes_pending_but_not_decided_recommendations(advisor):
    pending = rec(advisor, PLANTED["overweight_energy"])
    approved = rec(advisor, PLANTED["cash_drag"])
    decide(advisor, approved["id"], "accept")
    assert advisor.post("/api/analysis/runs").status_code == 200
    fresh = rec(advisor, PLANTED["overweight_energy"])
    assert fresh["id"] != pending["id"] and fresh["status"] == "pending_advisor" and fresh["version"] == 1
    assert decide(advisor, pending["id"], "accept").status_code == 409
    ids = [v["status"] for v in advisor.get(url(PLANTED["overweight_energy"])).json()["history"]["versions"]]
    assert ids == ["superseded", "pending_advisor"]
    assert advisor.get(f"/api/recommendations/{approved['id']}").json()["status"] == "approved"


@pytest.mark.parametrize("role,ok", [
    ("advisor", True), ("relationship_manager", True),
    ("portfolio_manager", False), ("compliance_officer", False), ("auditor", False),
    ("research_analyst", False), ("investment_committee", False), ("platform_owner", False),
])
def test_only_advisor_and_rm_can_decide(login, advisor, role, ok):
    r = rec(advisor, "C003")
    out = decide(login(role), r["id"], "reject", "because")
    assert (out.status_code == 200) is ok
    if not ok:
        assert out.status_code == 403


@pytest.mark.parametrize("role,ok", [
    ("advisor", True), ("portfolio_manager", True), ("compliance_officer", True), ("auditor", True),
    ("investment_committee", True), ("research_analyst", False), ("platform_owner", False),
])
def test_recommendation_read_permission(login, advisor, role, ok):
    r = rec(advisor, "C003")
    assert (login(role).get(f"/api/recommendations/{r['id']}").status_code == 200) is ok


def test_unknown_recommendation_is_404(advisor):
    assert advisor.get("/api/recommendations/99999").status_code == 404
    assert decide(advisor, 99999, "accept").status_code == 404


def test_restricted_instruments_are_never_bought(advisor, app):
    from app.db import RestrictionRow

    with app.state.session_factory() as db:  # restrict SHY for the cash-drag Client, then re-run
        db.add(RestrictionRow(client_id="C003", kind="instrument", value="SHY"))
        db.commit()
    assert advisor.post("/api/analysis/runs").status_code == 200
    buys = lines_by(rec(advisor, "C003"), "buy")
    assert "SHY" not in buys and "AGG" in buys


def test_configured_tolerance_band_decides_who_gets_a_recommendation(advisor, login):
    owner = login("platform_owner")
    wide = {"conservative": {"warn": 30, "breach": 40}, "moderate": {"warn": 30, "breach": 40}}
    assert owner.patch("/api/config", json={"tolerance_bands": wide}).status_code == 200
    assert advisor.post("/api/analysis/runs").status_code == 200
    assert rec(advisor, PLANTED["cash_drag"]) is None and rec(advisor, PLANTED["overweight_energy"]) is None
