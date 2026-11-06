"""Seam: the Analysis Run lifecycle through the HTTP API (ADR-0005). A run starts in the background; its Run Steps are read
back as snapshots. Timing is controlled only through the LLM the app is given."""
import json
import shutil
import sqlite3
import threading

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import audit
from app.analysis import run_analysis
from app.db import AuditEventRow
from app.llm import LlmError, LlmRequest, LlmResponse
from app.main import create_app
from app.market_data import MarketData
from app.research_seed import seed_research
from app.seeder import seed_clients
from tests.conftest import ROLES, SEED_PASSWORD
from tests.runs import RUNS, run_and_wait, wait_for_outcome
from tests.test_market_data import LOOKTHROUGH, SNAPSHOT
from tests.test_queue import seeded  # noqa: F401  (fixture)

KEYS = ["load_inputs", "score_portfolios", "record_run", "priority_narratives", "recommendation_narratives"]


@pytest.fixture
def advisor(login, seeded):  # noqa: F811
    return login("advisor")


def test_start_returns_202_and_a_snapshot_listing_all_five_run_steps(advisor):
    r = advisor.post(RUNS)
    assert r.status_code == 202, r.text
    snap = r.json()
    assert snap["actor_name"] == "advisor" and snap["started_at"] and snap["outcome"] is None
    assert [s["key"] for s in snap["steps"]] == KEYS
    assert [s["label"] for s in snap["steps"]] == [
        "Load inputs", "Score Portfolios", "Record run", "Priority narratives", "Recommendation narratives",
    ]
    assert {s["outcome"] for s in snap["steps"]} <= {"pending", "running", "done"}
    wait_for_outcome(advisor, snap["run_id"])


def test_a_run_ends_completed_with_every_run_step_done_and_timed(advisor):
    snap = wait_for_outcome(advisor, advisor.post(RUNS).json()["run_id"])
    assert snap["outcome"] == "completed" and snap["finished_at"]
    assert [s["outcome"] for s in snap["steps"]] == ["done"] * 5
    assert all(s["started_at"] and s["finished_at"] for s in snap["steps"])
    scoring = snap["steps"][1]
    assert (scoring["done"], scoring["total"]) == (25, 25)
    assert advisor.get("/api/queue").json()["run_id"] == snap["run_id"]


class BlockingLlm:
    """Holds the first LLM call until released. With approved research seeded, that is a Research Tilt inside Score
    Portfolios, so the run freezes part-way through scoring. Every call then fails, which costs only the AI output."""

    def __init__(self):
        self.entered, self.release = threading.Event(), threading.Event()

    def complete(self, request: LlmRequest) -> LlmResponse:
        self.entered.set()
        assert self.release.wait(30), "the test never released the LLM"
        raise LlmError("no AI output in this test")


@pytest.fixture
def frozen(app, advisor):
    """A run started by `advisor` and frozen part-way through Score Portfolios; released on teardown."""
    seed_research(app.state.session_factory)
    llm = BlockingLlm()
    app.state.llm = llm
    r = advisor.post(RUNS)
    assert r.status_code == 202, r.text
    assert llm.entered.wait(30)
    yield r.json()["run_id"], llm
    llm.release.set()
    wait_for_outcome(advisor, r.json()["run_id"])


def outcomes(snap):
    return [s["outcome"] for s in snap["steps"]]


def test_a_frozen_run_shows_the_earlier_steps_done_and_the_active_one_running(advisor, frozen):
    run_id, llm = frozen
    snap = advisor.get(f"{RUNS}/{run_id}").json()
    assert snap["outcome"] is None and snap["finished_at"] is None
    assert outcomes(snap) == ["done", "running", "pending", "pending", "pending"]
    scoring = snap["steps"][1]
    assert scoring["total"] == 25 and 0 <= scoring["done"] < 25
    assert scoring["started_at"] and scoring["finished_at"] is None
    llm.release.set()
    final = wait_for_outcome(advisor, run_id)
    assert final["outcome"] == "completed" and outcomes(final) == ["done"] * 5


def test_current_is_the_in_flight_run_and_204_when_idle(advisor, frozen):
    run_id, llm = frozen
    current = advisor.get(f"{RUNS}/current")
    assert current.status_code == 200 and current.json()["run_id"] == run_id
    llm.release.set()
    wait_for_outcome(advisor, run_id)
    assert advisor.get(f"{RUNS}/current").status_code == 204


@pytest.fixture
def colleague(login, seeded):  # noqa: F811
    return login("relationship_manager")  # before any run: a login writes, and an in-flight run holds the write lock


def test_a_second_start_while_a_run_is_in_flight_returns_409_with_that_run(colleague, frozen):
    run_id, _ = frozen
    r = colleague.post(RUNS)
    assert r.status_code == 409, r.text
    assert r.json()["run_id"] == run_id and r.json()["actor_name"] == "advisor"


def test_a_new_run_can_start_once_the_previous_one_has_finished(advisor):
    first = run_and_wait(advisor)
    assert run_and_wait(advisor) == first + 1


def test_without_an_llm_the_narrative_steps_are_skipped_and_the_run_completes(app, advisor):
    app.state.llm = None
    snap = wait_for_outcome(advisor, advisor.post(RUNS).json()["run_id"])
    assert snap["outcome"] == "completed"
    assert outcomes(snap) == ["done", "done", "done", "skipped", "skipped"]


def test_a_finished_run_is_still_served_after_later_runs(advisor):
    first = run_and_wait(advisor)
    run_and_wait(advisor)
    snap = advisor.get(f"{RUNS}/{first}").json()
    assert snap["run_id"] == first and snap["outcome"] == "completed" and outcomes(snap) == ["done"] * 5


def test_an_unknown_run_is_404(advisor):
    assert advisor.get(f"{RUNS}/9999").status_code == 404


DENIED = [r for r in ROLES if r not in ("advisor", "relationship_manager")]


@pytest.mark.parametrize("role", DENIED)
def test_roles_without_analysis_run_are_denied_every_run_endpoint_and_the_denial_is_audited(app, login, seeded, role):  # noqa: F811
    c = login(role)
    paths = [("post", RUNS), ("get", f"{RUNS}/current"), ("get", f"{RUNS}/1"), ("get", f"{RUNS}/1/events")]
    for method, path in paths:
        assert getattr(c, method)(path).status_code == 403, path
    with app.state.session_factory() as db:
        denied = [e for e in db.scalars(select(AuditEventRow).where(AuditEventRow.type == "access_denied"))]
    assert {e.actor_name for e in denied} == {role}
    assert sorted(json.loads(e.payload_json)["path"] for e in denied) == sorted(p for _, p in paths)


def run_events(app) -> list[tuple]:
    """The Audit Events from the first run's start on, comparable across databases: a parent is its position in that
    list, or for an earlier event (the seeded research) its type and payload. An Exchange hash covers the Exchange's own
    timestamp, so it differs between any two runs and is left out."""
    with app.state.session_factory() as db:
        events = list(db.scalars(select(AuditEventRow).order_by(AuditEventRow.id)))
    start = next(n for n, e in enumerate(events) if e.type == "analysis_run_started")
    ref = {e.id: (e.type, e.payload_json) for e in events[:start]} | {e.id: n for n, e in enumerate(events[start:])}
    return [
        (e.type, e.actor_kind, e.actor_name, e.actor_role,
         {k: v for k, v in json.loads(e.payload_json).items() if k != "exchange_hash"}, e.portfolio_id, e.client_id,
         e.recommendation_id, [ref[p] for p in json.loads(e.parent_ids_json)])
        for e in events[start:]
    ]


def test_a_background_run_records_the_same_queue_and_audit_events_as_a_synchronous_run(app, advisor, settings, tmp_path):
    seed_research(app.state.session_factory)
    run_and_wait(advisor)

    sync_dir = tmp_path / "sync"
    sync_dir.mkdir()
    sync_app = create_app(settings.model_copy(update={
        "database_url": f"sqlite:///{sync_dir / 'test.db'}", "market_data_snapshot_path": str(sync_dir / "snapshot.json"),
    }))
    shutil.copy(SNAPSHOT, sync_app.state.settings.market_data_snapshot_path)
    seed_clients(sync_app.state.session_factory, MarketData.load(SNAPSHOT, LOOKTHROUGH))
    seed_research(sync_app.state.session_factory)
    with sync_app.state.session_factory() as db:
        run_analysis(db, MarketData.load(SNAPSHOT, LOOKTHROUGH), audit.Actor.user("advisor", "advisor"), sync_app.state.llm)
    sync_advisor = TestClient(sync_app)
    assert sync_advisor.post("/api/auth/login", json={"username": "advisor", "password": SEED_PASSWORD}).status_code == 200

    assert advisor.get("/api/queue").json() == sync_advisor.get("/api/queue").json()
    background, synchronous = run_events(app), run_events(sync_app)
    assert any(e[0] == "recommendation_drafted" for e in background)
    assert background == synchronous


def test_a_database_from_before_run_outcomes_gets_them_and_its_completed_runs_read_as_completed(settings):
    path = settings.database_url.removeprefix("sqlite:///")
    with sqlite3.connect(path) as conn:  # the analysis_runs table as it was before this feature
        conn.execute(
            "CREATE TABLE analysis_runs (id INTEGER PRIMARY KEY, started_at VARCHAR, actor_name VARCHAR, as_of VARCHAR,"
            " config_json TEXT, completed BOOLEAN)"
        )
        conn.execute("INSERT INTO analysis_runs VALUES (1, '2026-01-01T00:00:00.000000Z', 'advisor', '2026-01-01', '{}', 1)")
    c = TestClient(create_app(settings))
    assert c.post("/api/auth/login", json={"username": "advisor", "password": SEED_PASSWORD}).status_code == 200
    snap = c.get(f"{RUNS}/1").json()
    assert snap["outcome"] == "completed" and outcomes(snap) == ["done"] * 5
