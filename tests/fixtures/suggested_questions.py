"""The seeded demo data, and the script that records every LLM reply the demo replays (sme-assistant spec: Replay
mode; ai-portfolio-rebalancing ticket 15). Re-record with `uv run python -m tests.fixtures.suggested_questions` after any
change to a prompt, a Screen Context builder, the platform brief, the seeded data or the walkthrough; it needs
`APP_LLM_API_KEY` (and the live endpoint and model settings, which must match RECORDED_MODEL and RECORDED_BASE_URL) in
the environment or `.env`.

The script seeds a fresh database exactly as the replay tests do and runs one Analysis Run, whose AI steps (priority
narratives, Research Tilts, rationale and memo) replay what is recorded and go live, with recording on, for anything
that is not. It then asks every Suggested Question on every demo screen, as every role that can read it, and finally
plays the scripted walkthrough (`scripts/walkthrough.py`) on a second fresh database, which records the calls a
modified Recommendation and the second Analysis Run make. Identical prompts are asked once. Recordings of these tasks
that nothing uses any more are removed. Audit screens are skipped: their context is never byte-identical (wall-clock
timestamps, and each turn adds an event), so their Suggested Questions do not replay. Insight extraction is never
re-recorded here: its recordings are keyed to the demo house view, not to the seed.
"""

import shutil
import sys
import tempfile
from pathlib import Path

from fastapi.testclient import TestClient

from app.exchanges import CapturingLlm
from app.llm import (
    LlmClient,
    LlmRequest,
    LlmResponse,
    OpenAICompatibleLlm,
    RecordedLlm,
    RecordingMissing,
    recording_key,
)
from app.main import create_app
from app.market_data import MarketData
from app.prompts import ASSISTANT_ANSWER, PRIORITY_NARRATIVE, RECOMMENDATION_NARRATIVE, RESEARCH_TILT
from app.rbac import ROLES
from app.research_seed import seed_research
from app.screen_context import SUGGESTED_QUESTIONS
from app.seeder import PLANTED, seed_clients
from app.settings import Settings
from tests.runs import run_and_wait

ROOT = Path(__file__).resolve().parents[2]
RECORDINGS = Path(__file__).parent / "llm"
SNAPSHOT = ROOT / "data" / "market_snapshot.json"
LOOKTHROUGH = ROOT / "data" / "fund_lookthrough.json"
SEED_PASSWORD = "test-only-password"
# The model and endpoint the committed recordings were made against. The Governance model card names both, so they
# are part of the governance prompt and its recording keys: changing them means re-recording.
RECORDED_MODEL = "anthropic/claude-sonnet-5.5"
RECORDED_BASE_URL = "https://openrouter.ai/api/v1/"
# The tasks this script records: the Analysis Run's AI steps and the Assistant.
RECORDED_TASKS = {t.name for t in (PRIORITY_NARRATIVE, RESEARCH_TILT, RECOMMENDATION_NARRATIVE, ASSISTANT_ANSWER)}


def replay_settings(directory: Path) -> Settings:
    """Settings for a throwaway app in recorded mode. Neither the developer's `.env` nor exported `APP_*` variables
    are read: what goes into a prompt (the model card names the model and endpoint, the row budget cuts lists) must be
    the same here, in CI and when recording."""
    # Init values outrank environment variables, so passing every field's default makes each one ignore the process
    # environment.
    values = {name: field.get_default(call_default_factory=True) for name, field in Settings.model_fields.items()}
    values |= {
        "llm_model": RECORDED_MODEL,
        "llm_base_url": RECORDED_BASE_URL,
        "database_url": f"sqlite:///{directory / 'test.db'}",
        "seed_user_password": SEED_PASSWORD,
        "market_data_snapshot_path": str(directory / "snapshot.json"),
        "llm_mode": "recorded",
        "llm_recordings_dir": str(RECORDINGS),
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


RECORDING_RUN_TIMEOUT = 1800.0  # seconds: a live Analysis Run makes ~40 LLM calls in turn


def seed_demo(app, run_timeout: float = 60) -> None:
    """The seeded data: the synthetic Clients, the research seeds and one completed Analysis Run by the advisor."""
    shutil.copy(SNAPSHOT, app.state.settings.market_data_snapshot_path)
    seed_clients(app.state.session_factory, MarketData.load(SNAPSHOT, LOOKTHROUGH))
    seed_research(app.state.session_factory, app.state.settings.seed_dir)
    run_and_wait(login(app, "advisor"), run_timeout)


def demo_screens(app) -> list[dict]:
    """The screen identities Suggested Questions are recorded on, exactly as the frontend publishes them: the Queue in
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


class ReplayOrLive:
    """Replays whatever is recorded; a call to a recorded task with no recording goes live and is recorded. Every
    other task only replays."""

    def __init__(self, live: OpenAICompatibleLlm):
        self.recorded = RecordedLlm(RECORDINGS)
        self.live = live
        self.model = live.model
        self.used: set[str] = set()

    def complete(self, request: LlmRequest) -> LlmResponse:
        try:
            return self.recorded.complete(request)
        except RecordingMissing:
            if request.task not in RECORDED_TASKS:
                raise
            return self.live.complete(request)
        finally:
            if request.task in RECORDED_TASKS:
                self.used.add(recording_key(request))


def record() -> int:
    env = Settings()
    if not env.llm_api_key:
        print("APP_LLM_API_KEY must be set to record", file=sys.stderr)
        return 1
    if (env.llm_model, env.llm_base_url) != (RECORDED_MODEL, RECORDED_BASE_URL):
        print(
            f"record against {RECORDED_MODEL} at {RECORDED_BASE_URL}, or change RECORDED_MODEL and RECORDED_BASE_URL",
            file=sys.stderr,
        )
        return 1
    live = OpenAICompatibleLlm(
        base_url=env.llm_base_url, api_key=env.llm_api_key, model=env.llm_model, record_dir=RECORDINGS
    )
    client = ReplayOrLive(live)
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(lift_question_limits(replay_settings(Path(tmp))))
        inner: LlmClient = client
        app.state.llm = CapturingLlm(inner, app.state.session_factory, mode="recorded")
        seed_demo(app, RECORDING_RUN_TIMEOUT)
        failures = []
        for screen in demo_screens(app):
            for role in ROLES:
                c = login(app, role)  # a fresh login per role: each Question starts its own Conversation
                for question in SUGGESTED_QUESTIONS[screen["kind"]]:
                    turn = c.post("/api/assistant/questions", json={"question": question, "screen": screen}).json()
                    print(f"{turn['outcome']:9} {role:22} {screen['kind']:15} {question}")
                    if turn["outcome"] == "failed":
                        failures.append((role, screen, question))
    from scripts.walkthrough import walk  # here, not at the top: the walkthrough imports this module

    broken = [check for check in walk(client, run_timeout=RECORDING_RUN_TIMEOUT) if not check.ok]
    for check in broken:
        print(f"walkthrough FAIL {check.act}: {check.claim} [{check.evidence}]")
    stale = [
        p
        for task in RECORDED_TASKS
        for p in RECORDINGS.glob(f"{task}-*.json")
        if p.stem.split("-")[-1] not in client.used
    ]
    for path in stale:
        path.unlink()
    print(
        f"{len(client.used)} recordings in use, {len(stale)} stale removed, {len(failures)} failed Questions, "
        f"{len(broken)} failed walkthrough claims"
    )
    return 1 if failures or broken else 0


if __name__ == "__main__":
    sys.exit(record())
