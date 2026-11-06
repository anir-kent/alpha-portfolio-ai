"""Seam: Portfolio drill-down through the HTTP API against seeded data."""

import pytest
from sqlalchemy import select

from app.db import AuditEventRow
from app.seeder import PLANTED
from tests.runs import run_and_wait
from tests.test_queue import QUEUE, seeded  # noqa: F401  (fixture)


def url(cid):
    return f"/api/portfolios/{cid}"


@pytest.fixture
def advisor(login, seeded):  # noqa: F811
    c = login("advisor")
    run_and_wait(c)
    return c


def sector(body, name):
    return next(s for s in body["sector_exposure"] if s["sector"] == name)


def test_holdings_are_valued_and_weights_sum_to_100(advisor):
    body = advisor.get(url(PLANTED["clean"])).json()
    hs = body["holdings"]
    assert hs and all(h["market_value"] == pytest.approx(h["quantity"] * h["price"]) for h in hs)
    assert sum(h["weight_pct"] for h in hs) == pytest.approx(100)
    assert body["total_value"] == pytest.approx(sum(h["market_value"] for h in hs))


def test_look_through_matches_reference_weights_on_planted_scenarios(advisor):
    # Reference = planted spec weights x fund look-through (SPY: IT 31%, Energy 3%); quantities are whole units.
    energy = sector(advisor.get(url(PLANTED["overweight_energy"])).json(), "Energy")
    assert energy["weight_pct"] == pytest.approx(30.45, abs=0.5)  # XOM 15 + XLE 15 + 15% x SPY 3%
    assert energy["direct_pct"] == pytest.approx(15, abs=0.5)
    assert energy["via_funds_pct"] == pytest.approx(15.45, abs=0.5)
    tech = sector(advisor.get(url(PLANTED["heavy_tech"])).json(), "Information Technology")
    assert tech["weight_pct"] == pytest.approx(57.1, abs=0.5)  # AAPL+MSFT+NVDA 42 + XLK 12 + 10% x SPY 31%
    assert tech["via_funds_pct"] == pytest.approx(15.1, abs=0.5)


def test_sector_exposure_sums_to_100_and_is_sorted_largest_first(advisor):
    exp = advisor.get(url(PLANTED["heavy_tech"])).json()["sector_exposure"]
    assert sum(s["weight_pct"] for s in exp) == pytest.approx(100)
    assert [s["weight_pct"] for s in exp] == sorted((s["weight_pct"] for s in exp), reverse=True)
    assert all(s["weight_pct"] == pytest.approx(s["direct_pct"] + s["via_funds_pct"]) for s in exp)


def test_drift_agrees_with_the_queue(advisor):
    q = next(i for i in advisor.get(QUEUE).json()["items"] if i["client_id"] == PLANTED["cash_drag"])
    d = advisor.get(url(PLANTED["cash_drag"])).json()["drift"]
    assert d["portfolio_drift_pp"] == q["portfolio_drift_pp"]
    assert d["asset_classes"] == q["asset_class_drift"]
    assert d["tolerance_band"] == {"warn": 2, "breach": 4}  # conservative
    assert advisor.get(QUEUE).json()["run_id"] == d["run_id"]


def test_actual_allocation_matches_holdings(advisor):
    body = advisor.get(url(PLANTED["cash_drag"])).json()
    for ac in body["drift"]["asset_classes"]:
        held = sum(h["weight_pct"] for h in body["holdings"] if h["asset_class"] == ac["asset_class"])
        assert ac["actual_pct"] == pytest.approx(held, abs=0.01)


def test_drift_is_null_before_any_run(login, seeded):  # noqa: F811
    body = login("advisor").get(url("C001")).json()
    assert body["drift"] is None and body["holdings"]


def test_client_context_restrictions_and_empty_history(advisor):
    body = advisor.get(url(PLANTED["restricted_breach"])).json()
    c = body["client"]
    assert c["risk_profile"] == "growth" and c["objective"] and c["horizon_years"] > 0
    assert c["liquidity_needs_pct"] >= 0
    assert {"kind": "instrument", "value": "XOM"} in body["restrictions"]
    assert body["history"] == {"versions": [], "decisions": []}


def test_unknown_portfolio_is_404(advisor):
    assert advisor.get(url("C999")).status_code == 404


def test_advisor_sees_sensitive_fields(advisor):
    c = advisor.get(url("C001")).json()["client"]
    assert c["name"] and c["email"]


@pytest.mark.parametrize("role", ["relationship_manager", "portfolio_manager"])
def test_roles_without_pii_see_masked_fields_but_everything_else(login, advisor, role):
    c = login(role)
    r = c.get(url("C001"))
    assert r.status_code == 200
    client = r.json()["client"]
    assert client["name"] is None and client["email"] is None
    assert client["risk_profile"] and r.json()["holdings"]


@pytest.mark.parametrize(
    "role,ok",
    [
        ("advisor", True),
        ("relationship_manager", True),
        ("portfolio_manager", True),
        ("compliance_officer", True),
        ("auditor", True),
        ("research_analyst", False),
        ("investment_committee", False),
        ("platform_owner", False),
    ],
)
def test_portfolio_read_permission(login, seeded, role, ok):  # noqa: F811
    assert (login(role).get(url("C001")).status_code == 200) is ok


def test_denied_access_is_audited(login, seeded, app):  # noqa: F811
    login("research_analyst").get(url("C001"))
    with app.state.session_factory() as db:
        e = db.scalar(select(AuditEventRow).where(AuditEventRow.type == "access_denied"))
        assert e and "portfolio:read" in e.payload_json
