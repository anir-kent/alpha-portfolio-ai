"""Seam: analysis run + ranked queue through the HTTP API against seeded data."""
import shutil

import pytest
from sqlalchemy import select

from app import audit
from app.db import AuditEventRow
from app.market_data import MarketData
from app.seeder import PLANTED, seed_clients
from tests.runs import RUNS, run_and_wait
from tests.test_market_data import LOOKTHROUGH, SNAPSHOT

QUEUE = "/api/queue"


@pytest.fixture
def seeded(app, settings):
    shutil.copy(SNAPSHOT, settings.market_data_snapshot_path)
    seed_clients(app.state.session_factory, MarketData.load(SNAPSHOT, LOOKTHROUGH))
    return app


@pytest.fixture
def advisor(login, seeded):
    c = login("advisor")
    run_and_wait(c)
    return c


def rows(c, **params):
    r = c.get(QUEUE, params=params)
    assert r.status_code == 200, r.text
    return r.json()["items"]


def test_queue_is_empty_before_any_analysis_run(login, seeded):
    assert login("advisor").get(QUEUE).json()["items"] == []


def test_run_scores_every_portfolio_and_queue_is_ranked_by_score(advisor):
    items = rows(advisor)
    assert len(items) == 25
    scores = [i["score"] for i in items]
    assert scores == sorted(scores, reverse=True)


def test_planted_scenarios_rank_as_expected_and_clean_portfolio_is_low(advisor):
    items = rows(advisor)
    rank = {i["client_id"]: n for n, i in enumerate(items)}
    by = {i["client_id"]: i for i in items}
    assert rank[PLANTED["cash_drag"]] < rank[PLANTED["clean"]]
    assert rank[PLANTED["overweight_energy"]] < rank[PLANTED["clean"]]
    assert by[PLANTED["cash_drag"]]["label"] == "High"
    assert by[PLANTED["overweight_energy"]]["label"] == "High"
    assert by[PLANTED["clean"]]["label"] == "Low"
    assert by[PLANTED["clean"]]["score"] < 10


def test_every_row_carries_breakdown_drift_and_sla_flag(advisor):
    row = next(i for i in rows(advisor) if i["client_id"] == PLANTED["cash_drag"])
    comps = {c["name"]: c for c in row["components"]}
    assert set(comps) == {"drift", "risk", "opportunity", "urgency"}
    assert comps["opportunity"]["raw"] == 0
    assert row["score"] == pytest.approx(sum(c["points"] for c in row["components"]), abs=0.1)
    assert row["portfolio_drift_pp"] == pytest.approx(25, abs=0.5)
    assert {c["asset_class"]: c["status"] for c in row["asset_class_drift"]}["cash"] == "breach"
    assert row["risk_profile"] == "conservative"
    assert row["days_past_due"] == 30 and row["sla_breached"] is True  # planted: due 30 days ago, SLA 30


def test_config_weights_change_scores(advisor, login):
    before = {i["client_id"]: i["score"] for i in rows(advisor)}
    owner = login("platform_owner")
    owner.patch("/api/config", json={"priority_weights": {"drift": 0, "risk": 0, "opportunity": 0, "urgency": 1}})
    run_and_wait(advisor)
    after = {i["client_id"]: i for i in rows(advisor)}
    assert after[PLANTED["clean"]]["score"] == 0
    assert after[PLANTED["cash_drag"]]["score"] == 100
    assert after[PLANTED["cash_drag"]]["score"] != before[PLANTED["cash_drag"]]


def test_new_run_supersedes_the_previous_one(advisor):
    first = advisor.get(QUEUE).json()["run_id"]
    second = run_and_wait(advisor)
    assert second != first
    body = advisor.get(QUEUE).json()
    assert body["run_id"] == second and len(body["items"]) == 25


def test_run_is_audited_with_started_event_and_one_scored_event_per_portfolio(advisor, app):
    with app.state.session_factory() as db:
        events = list(db.scalars(select(AuditEventRow).order_by(AuditEventRow.id)))
        started = [e for e in events if e.type == "analysis_run_started"]
        scored = [e for e in events if e.type == "priority_scored"]
        assert len(started) == 1 and len(scored) == 25
        assert started[0].actor_name == "advisor"
        assert all(started[0].id in __import__("json").loads(e.parent_ids_json) for e in scored)
        assert all(e.portfolio_id and e.client_id for e in scored)
        assert audit.verify(db).valid


def test_filter_by_label_and_risk_profile(advisor):
    high = rows(advisor, label="High")
    assert high and all(i["label"] == "High" for i in high)
    cons = rows(advisor, risk_profile="conservative")
    assert cons and all(i["risk_profile"] == "conservative" for i in cons)


def test_filter_by_review_due_range_and_sort_by_review_due(advisor):
    items = rows(advisor, sort="review_due", order="asc")
    dues = [i["review_due"] for i in items]
    assert dues == sorted(dues)
    mid = dues[len(dues) // 2]
    later = rows(advisor, review_due_from=mid)
    assert later and all(i["review_due"] >= mid for i in later)
    earlier = rows(advisor, review_due_to=mid)
    assert all(i["review_due"] <= mid for i in earlier)


def test_sla_breached_filter(advisor):
    breached = rows(advisor, sla_breached="true")
    assert breached and all(i["sla_breached"] for i in breached)


def test_client_name_is_masked_without_pii_permission(login, advisor):
    assert next(i for i in rows(advisor) if i["client_id"] == "C001")["client_name"]
    rm = login("relationship_manager")
    assert next(i for i in rows(rm) if i["client_id"] == "C001")["client_name"] is None


@pytest.mark.parametrize("role,ok", [
    ("advisor", True), ("relationship_manager", True),
    ("portfolio_manager", False), ("compliance_officer", False), ("auditor", False),
    ("research_analyst", False), ("investment_committee", False), ("platform_owner", False),
])
def test_only_advisor_and_rm_can_run_and_read_the_queue(login, seeded, role, ok):
    c = login(role)
    if ok:
        run_and_wait(c)
    else:
        assert c.post(RUNS).status_code == 403
    assert (c.get(QUEUE).status_code == 200) is ok


def test_denied_attempts_are_audited(login, seeded, app):
    login("auditor").get(QUEUE)
    with app.state.session_factory() as db:
        assert db.scalar(select(AuditEventRow).where(AuditEventRow.type == "access_denied"))


def test_cli_runs_analysis(seeded, settings):
    from app.analysis import main
    assert main(settings) == 25
