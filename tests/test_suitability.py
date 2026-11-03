"""Seam: Suitability Rules through the HTTP API (drill-down, queue, audit) against seeded planted scenarios.

Expected numbers are the planted weights in app/seeder.py (whole-unit quantities, hence the tolerances) and the
default limits in the spec: equity cap by Risk Profile, 10% single position, 30% sector, cash floor by Risk Profile.
"""
import json

import pytest
from sqlalchemy import select

from app import audit
from app.db import AuditEventRow
from app.seeder import PLANTED
from tests.test_portfolio import url
from tests.test_queue import QUEUE, rows, seeded  # noqa: F401  (fixture)

RULE_IDS = ["SR-01", "SR-02", "SR-03", "SR-04", "SR-05", "SR-06", "SR-07"]


@pytest.fixture
def advisor(login, seeded):  # noqa: F811
    c = login("advisor")
    assert c.post("/api/analysis/runs").status_code == 200
    return c


def suitability(c, cid):
    return c.get(url(cid)).json()["suitability"]


def rule(c, cid, rule_id):
    return next(r for r in suitability(c, cid)["rules"] if r["rule_id"] == rule_id)


def finding(r, subject):
    return next(f for f in r["findings"] if f["subject"] == subject)


def test_every_portfolio_reports_all_seven_rules_with_name_status_and_message(advisor):
    s = suitability(advisor, PLANTED["clean"])
    assert [r["rule_id"] for r in s["rules"]] == RULE_IDS
    assert all(r["name"] and r["message"] and r["status"] in ("pass", "warning", "breach") for r in s["rules"])


def test_suitability_is_null_before_any_run(login, seeded):  # noqa: F811
    assert login("advisor").get(url("C001")).json()["suitability"] is None


@pytest.mark.parametrize("key", ["clean", "cash_drag"])
def test_clean_portfolios_pass_every_rule(advisor, key):
    s = suitability(advisor, PLANTED[key])
    assert s["status"] == "pass"
    assert [r["status"] for r in s["rules"]] == ["pass"] * 7


def test_restricted_instrument_is_a_breach_naming_the_rule_and_instrument(advisor):
    r = rule(advisor, PLANTED["restricted_breach"], "SR-05")
    assert r["status"] == "breach"
    f = finding(r, "XOM")
    assert f["status"] == "breach" and f["actual"] == pytest.approx(6.0, abs=0.1)
    assert "XOM" in r["message"]
    assert suitability(advisor, PLANTED["restricted_breach"])["status"] == "breach"


def test_restricted_scenario_breaches_nothing_else_but_warns_on_liquidity(advisor):
    rules = {r["rule_id"]: r for r in suitability(advisor, PLANTED["restricted_breach"])["rules"]}
    assert [i for i, r in rules.items() if r["status"] == "breach"] == ["SR-05"]
    cash = finding(rules["SR-04"], "cash")  # 5.0% cash covers the 2% growth floor but not 8.9% liquidity needs
    assert rules["SR-04"]["status"] == "warning"
    assert cash["actual"] == pytest.approx(5.0, abs=0.1) and cash["limit"] == pytest.approx(8.9)


def test_max_equity_share_by_risk_profile(advisor):
    r = rule(advisor, PLANTED["overweight_energy"], "SR-01")  # moderate: 60% equity vs 55% cap
    assert r["status"] == "breach"
    f = finding(r, "equity")
    assert f["actual"] == pytest.approx(60.0, abs=0.1) and f["limit"] == 55
    assert rule(advisor, PLANTED["heavy_tech"], "SR-01")["status"] == "pass"  # growth: 70% vs 80% cap


def test_single_position_limit_names_every_offending_instrument(advisor):
    r = rule(advisor, PLANTED["heavy_tech"], "SR-02")
    assert r["status"] == "breach"
    assert {f["subject"] for f in r["findings"] if f["status"] == "breach"} == {"AAPL", "MSFT", "NVDA"}
    assert finding(r, "AAPL")["actual"] == pytest.approx(15.0, abs=0.1) and finding(r, "AAPL")["limit"] == 10
    assert finding(r, "NVDA")["actual"] == pytest.approx(12.0, abs=0.1)


def test_single_position_limit_ignores_diversified_funds(advisor):
    # C004 holds 30% SPY; only single names count, and its largest (AAPL/MSFT, 8%) is below the 9% warning line.
    assert rule(advisor, PLANTED["restricted_breach"], "SR-02")["status"] == "pass"


def test_sector_concentration_uses_look_through(advisor):
    r = rule(advisor, PLANTED["heavy_tech"], "SR-03")  # 42 direct + 12 XLK + 10% x SPY 31%
    assert r["status"] == "breach"
    f = finding(r, "Information Technology")
    assert f["actual"] == pytest.approx(57.1, abs=0.5) and f["limit"] == 30
    energy = rule(advisor, PLANTED["overweight_energy"], "SR-03")  # 30.45% vs 30% cap
    assert energy["status"] == "breach"
    assert finding(energy, "Energy")["actual"] == pytest.approx(30.45, abs=0.5)


def test_sector_concentration_ignores_cash_and_fixed_income_pseudo_sectors(advisor):
    f = rule(advisor, PLANTED["cash_drag"], "SR-03")["findings"][0]
    assert f["subject"] not in ("Cash", "Fixed Income") and f["actual"] < 10


def test_cash_below_the_policy_floor_is_a_breach(advisor, login):
    owner = login("platform_owner")
    owner.patch("/api/config", json={"suitability": {"min_cash_pct": {"growth": 6}}})
    advisor.post("/api/analysis/runs")
    r = rule(advisor, PLANTED["heavy_tech"], "SR-04")  # 5.0% cash vs raised 6% floor
    assert r["status"] == "breach"
    assert finding(r, "cash")["actual"] == pytest.approx(5.0, abs=0.1) and finding(r, "cash")["limit"] == 6


def test_horizon_check_flags_equity_heavy_portfolio_with_a_short_horizon(advisor, login):
    assert rule(advisor, PLANTED["overweight_energy"], "SR-06")["status"] == "pass"  # 5-year horizon, not short
    login("platform_owner").patch("/api/config", json={"suitability": {"horizon_short_years": 6}})
    advisor.post("/api/analysis/runs")
    r = rule(advisor, PLANTED["overweight_energy"], "SR-06")  # now short: 60% equity vs 40% cap
    assert r["status"] == "breach"
    f = finding(r, "equity")
    assert f["actual"] == pytest.approx(60.0, abs=0.1) and f["limit"] == 40
    assert "5" in r["message"]


def test_taxable_gain_warning_never_breaches(advisor, login):
    r = rule(advisor, PLANTED["overweight_energy"], "SR-07")
    assert r["status"] == "pass" and finding(r, "taxable gains")["actual"] == pytest.approx(9.4, abs=0.2)
    login("platform_owner").patch("/api/config", json={"suitability": {"taxable_gain_pct": 5}})
    advisor.post("/api/analysis/runs")
    r = rule(advisor, PLANTED["overweight_energy"], "SR-07")
    assert r["status"] == "warning" and finding(r, "taxable gains")["limit"] == 5
    for cid in (PLANTED["heavy_tech"], PLANTED["restricted_breach"], PLANTED["clean"]):
        assert rule(advisor, cid, "SR-07")["status"] in ("pass", "warning")


def test_value_close_to_a_limit_is_a_warning(advisor, login):
    login("platform_owner").patch("/api/config", json={"suitability": {"single_position_pct": 8.5}})
    advisor.post("/api/analysis/runs")
    r = rule(advisor, PLANTED["restricted_breach"], "SR-02")  # AAPL/MSFT 8.0% is within 90% of an 8.5% limit
    assert r["status"] == "warning" and finding(r, "AAPL")["status"] == "warning"


def test_sector_restriction_breaches_on_direct_holdings_and_warns_on_fund_exposure(advisor, app):
    from app.db import RestrictionRow

    with app.state.session_factory() as db:
        db.add(RestrictionRow(client_id=PLANTED["overweight_energy"], kind="sector", value="Energy"))
        db.add(RestrictionRow(client_id=PLANTED["clean"], kind="sector", value="Energy"))
        db.commit()
    advisor.post("/api/analysis/runs")
    r = rule(advisor, PLANTED["overweight_energy"], "SR-05")
    assert r["status"] == "breach" and finding(r, "XOM")["status"] == "breach"
    clean = rule(advisor, PLANTED["clean"], "SR-05")  # no Energy stock, only SPY's small look-through slice
    assert clean["status"] == "warning" and finding(clean, "Energy")["status"] == "warning"


def test_suitability_evaluation_is_audited_with_its_results(advisor, app):
    with app.state.session_factory() as db:
        events = list(db.scalars(select(AuditEventRow).where(AuditEventRow.type == "suitability_evaluated")))
        started = db.scalar(select(AuditEventRow).where(AuditEventRow.type == "analysis_run_started"))
        assert len(events) == 25
        e = next(e for e in events if e.portfolio_id == PLANTED["restricted_breach"])
        payload = json.loads(e.payload_json)
        assert payload["status"] == "breach" and [r["rule_id"] for r in payload["rules"]] == RULE_IDS
        assert any(f["subject"] == "XOM" for r in payload["rules"] for f in r["findings"])
        assert started.id in json.loads(e.parent_ids_json) and e.client_id == PLANTED["restricted_breach"]
        scored = db.scalar(select(AuditEventRow).where(
            AuditEventRow.type == "priority_scored", AuditEventRow.portfolio_id == PLANTED["restricted_breach"]))
        assert e.id in json.loads(scored.parent_ids_json)  # the score is traceable to its suitability result
        assert audit.verify(db).valid


def test_priority_risk_component_uses_suitability_results(advisor):
    by = {i["client_id"]: i for i in rows(advisor)}

    def risk(cid):
        return next(c for c in by[cid]["components"] if c["name"] == "risk")["raw"]

    assert risk(PLANTED["heavy_tech"]) == 100  # two breaches (SR-02, SR-03) + a liquidity warning, capped
    assert risk(PLANTED["restricted_breach"]) == 65  # one breach (50) + one warning (15)
    assert risk(PLANTED["clean"]) == 0


def test_suitability_driven_portfolios_outrank_the_clean_one(advisor):
    rank = {i["client_id"]: n for n, i in enumerate(rows(advisor))}
    assert rank[PLANTED["heavy_tech"]] < rank[PLANTED["clean"]]
    assert rank[PLANTED["restricted_breach"]] < rank[PLANTED["clean"]]
    by = {i["client_id"]: i for i in rows(advisor)}
    assert by[PLANTED["restricted_breach"]]["score"] > by[PLANTED["clean"]]["score"] + 10


def test_suitability_is_readable_by_compliance_and_denied_to_roles_without_portfolio_read(login, advisor):
    assert login("compliance_officer").get(url("C001")).json()["suitability"]["status"] == "breach"
    assert login("research_analyst").get(url("C001")).status_code == 403
