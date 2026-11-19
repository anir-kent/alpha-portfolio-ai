"""The seeded demo data every test and script builds on: the synthetic Clients, the research seeds and one Analysis Run
by the advisor, and the screens the Assistant's Suggested Questions are asked on."""

import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from app.market_data import MarketData
from app.research_seed import seed_research
from app.seeder import PLANTED, seed_clients
from app.settings import Settings
from tests.runs import run_and_wait

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "data" / "market_snapshot.json"
LOOKTHROUGH = ROOT / "data" / "fund_lookthrough.json"
SEED_PASSWORD = "test-only-password"


def demo_settings(directory: Path) -> Settings:
    """Settings for a throwaway app on a database under `directory`. Neither the developer's `.env` nor exported `APP_*`
    variables are read, so a local run sees what CI sees."""
    # Init values outrank environment variables, so passing every field's default makes each one ignore the process
    # environment.
    values = {name: field.get_default(call_default_factory=True) for name, field in Settings.model_fields.items()}
    values |= {
        "database_url": f"sqlite:///{directory / 'test.db'}",
        "seed_user_password": SEED_PASSWORD,
        "market_data_snapshot_path": str(directory / "snapshot.json"),
        "seed_dir": str(ROOT / "data" / "seed"),
    }
    return Settings(_env_file=None, **values)  # `_env_file=None`: a pydantic-settings init option, read no .env


def lift_question_limits(settings: Settings) -> Settings:
    """Lifts the per-Conversation and per-hour Question limits, for sweeps that ask every Suggested Question on every
    demo screen as every role: far more than one user may ask in an hour."""
    settings.assistant_questions_per_conversation = 10_000
    settings.assistant_questions_per_hour = 10_000
    return settings


def login(app, role: str) -> TestClient:
    c = TestClient(app)
    r = c.post("/api/auth/login", json={"username": role, "password": SEED_PASSWORD})
    assert r.status_code == 200, r.text
    return c


def seed_demo(app, run_timeout: float = 60) -> None:
    """The seeded data: the synthetic Clients, the research seeds and one completed Analysis Run by the advisor."""
    shutil.copy(SNAPSHOT, app.state.settings.market_data_snapshot_path)
    seed_clients(app.state.session_factory, MarketData.load(SNAPSHOT, LOOKTHROUGH))
    seed_research(app.state.session_factory, app.state.settings.seed_dir)
    run_and_wait(login(app, "advisor"), run_timeout)


def demo_screens(app) -> list[dict]:
    """The screen identities Suggested Questions are asked on, exactly as the frontend publishes them: the Queue in
    its default sort, each planted Portfolio and its Recommendation, and the list screens with nothing selected."""
    advisor = login(app, "advisor")
    screens: list[dict] = [{"kind": "queue", "entity_ids": {"sort": "score"}, "selected_item": None}]
    for portfolio_id in PLANTED.values():
        screens.append({"kind": "portfolio", "entity_ids": {"portfolio_id": portfolio_id}, "selected_item": None})
        rec = advisor.get(f"/api/portfolios/{portfolio_id}").json().get("recommendation")
        if rec:
            ids = {"recommendation_id": str(rec["id"]), "portfolio_id": rec["portfolio_id"]}
            screens.append({"kind": "recommendation", "entity_ids": ids, "selected_item": None})
    for kind in ("approvals", "exchanges", "governance", "config", "health"):
        screens.append({"kind": kind, "entity_ids": {}, "selected_item": None})
    return screens
