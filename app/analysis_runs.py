"""Background Analysis Runs and their progress (ADR-0005).

`AnalysisRuns.start` commits the run row, then runs `run_analysis` on its own thread with its own Session. Only one run is
in flight per process. Run Step progress lives in a `ProgressRegistry` in memory, never in the database while the run is
going: the scoring transaction holds the only write lock (ADR-0004). When the run ends, its outcome and Run Step results
are saved on the run row.
"""
import json
import logging
import threading
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import audit
from app.analysis import open_run, run_analysis
from app.db import AnalysisRunRow
from app.llm import LlmClient
from app.market_data import MarketData
from app.run_steps import RUN_STEP_KEYS, RUN_STEPS, SCORING_STEP_KEYS, RunStepKey, step

log = logging.getLogger(__name__)

StepOutcome = Literal["pending", "running", "done", "failed", "skipped"]
RunOutcome = Literal["completed", "completed_with_warnings", "failed", "interrupted"]


class RunStepOut(BaseModel):
    key: RunStepKey
    label: str
    outcome: StepOutcome
    started_at: str | None = None
    finished_at: str | None = None
    error: str | None = None
    done: int | None = None  # Score Portfolios only: Portfolios scored so far, of `total`
    total: int | None = None


class RunSnapshot(BaseModel):
    """The whole state of one Analysis Run: what a client needs to draw the Run Analysis modal."""

    run_id: int
    actor_name: str
    started_at: str
    finished_at: str | None
    outcome: RunOutcome | None  # null while the run is in flight
    steps: list[RunStepOut]


def _now() -> str:
    return audit.format_ts(datetime.now(timezone.utc))


class ProgressRegistry:
    """The in-flight run's latest snapshot, and the last finished one, each with a sequence number for its run. Thread-safe.
    A broker can replace this for more than one API process (ADR-0005)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._in_flight: tuple[RunSnapshot, int] | None = None
        self._finished: tuple[RunSnapshot, int] | None = None

    def publish(self, snapshot: RunSnapshot) -> int:
        """Store `snapshot` as its run's latest state; returns the run's new sequence number."""
        with self._lock:
            latest = self._latest(snapshot.run_id)
            seq = latest[1] + 1 if latest else 1
            entry = (snapshot.model_copy(deep=True), seq)
            if snapshot.outcome is None:
                self._in_flight = entry
            else:
                self._finished = entry
                if self._in_flight and self._in_flight[0].run_id == snapshot.run_id:
                    self._in_flight = None
            return seq

    def latest(self, run_id: int) -> tuple[RunSnapshot, int] | None:
        with self._lock:
            return self._latest(run_id)

    def in_flight(self) -> RunSnapshot | None:
        with self._lock:
            return self._in_flight[0] if self._in_flight else None

    def _latest(self, run_id: int) -> tuple[RunSnapshot, int] | None:
        for entry in (self._in_flight, self._finished):
            if entry and entry[0].run_id == run_id:
                return entry
        return None


class SnapshotReporter:
    """A RunStepReporter that keeps the run's snapshot and publishes it on every change."""

    def __init__(self, registry: ProgressRegistry, run: AnalysisRunRow) -> None:
        self._registry = registry
        self.snapshot = RunSnapshot(
            run_id=run.id, actor_name=run.actor_name, started_at=run.started_at, finished_at=None, outcome=None,
            steps=[RunStepOut(key=s.key, label=s.label, outcome="pending") for s in RUN_STEPS],
        )
        self._publish()

    def _step(self, key: RunStepKey) -> RunStepOut:
        return self.snapshot.steps[RUN_STEP_KEYS.index(key)]

    def _publish(self) -> None:
        self._registry.publish(self.snapshot)

    def step_started(self, key: RunStepKey) -> None:
        step = self._step(key)
        step.outcome, step.started_at = "running", _now()
        self._publish()

    def step_finished(self, key: RunStepKey) -> None:
        self._end(key, "done")

    def step_failed(self, key: RunStepKey) -> None:
        self._step(key).error = step(key).failure_message
        self._end(key, "failed")

    def step_skipped(self, key: RunStepKey) -> None:
        self._step(key).outcome = "skipped"
        self._publish()

    def portfolios_scored(self, done: int, total: int) -> None:
        step = self._step("score_portfolios")
        step.done, step.total = done, total
        self._publish()

    def _end(self, key: RunStepKey, outcome: StepOutcome) -> None:
        step = self._step(key)
        step.outcome, step.finished_at = outcome, _now()
        self._publish()

    def failed_step_label(self) -> str | None:
        return next((s.label for s in self.snapshot.steps if s.outcome == "failed"), None)

    def outcome(self) -> RunOutcome:
        """Completed only if the results were recorded; with warnings if a later (AI) step failed."""
        if self._step("record_run").outcome != "done":
            return "failed"
        return "completed_with_warnings" if any(s.outcome == "failed" for s in self.snapshot.steps) else "completed"

    def finish(self, outcome: RunOutcome, finished_at: str) -> None:
        self.snapshot.outcome, self.snapshot.finished_at = outcome, finished_at
        self._publish()


def snapshot_from_row(run: AnalysisRunRow) -> RunSnapshot:
    """A finished run's snapshot, as saved on its row. A row saved before Run Steps were recorded shows them all
    done if its results were recorded, pending otherwise."""
    if run.steps_json:
        steps = [RunStepOut.model_validate(s) for s in json.loads(run.steps_json)]
    else:
        steps = [RunStepOut(key=s.key, label=s.label, outcome="done" if run.completed else "pending") for s in RUN_STEPS]
    return RunSnapshot(
        run_id=run.id, actor_name=run.actor_name, started_at=run.started_at, finished_at=run.finished_at,
        outcome=run.outcome, steps=steps,  # validated: a stored outcome is always a RunOutcome
    )


def save_outcome(run: AnalysisRunRow, outcome: RunOutcome, finished_at: str, steps: list[RunStepOut]) -> None:
    run.outcome, run.finished_at = outcome, finished_at
    run.steps_json = json.dumps([s.model_dump() for s in steps])


def mark_stranded_runs_interrupted(session_factory: sessionmaker) -> None:
    """At startup, no run can be in flight (one API process, ADR-0005): a row with no outcome is a run the process died
    in. Mark it interrupted. Its in-memory progress is gone; what its row says is what happened: the scoring steps are
    done only if their transaction committed (`completed`), and every other step never finished."""
    finished_at = _now()
    with session_factory() as db:
        for run in db.scalars(select(AnalysisRunRow).where(AnalysisRunRow.outcome.is_(None))):
            steps = [
                RunStepOut(key=s.key, label=s.label, outcome="done" if run.completed and s.key in SCORING_STEP_KEYS else "skipped")
                for s in RUN_STEPS
            ]
            save_outcome(run, "interrupted", finished_at, steps)
            log.warning("Analysis Run %s: interrupted by a restart", run.id)
        db.commit()


class AnalysisRuns:
    """Starts Analysis Runs in the background, one at a time, and answers what a run looks like now."""

    def __init__(self, session_factory: sessionmaker, registry: ProgressRegistry | None = None) -> None:
        self._session_factory = session_factory
        self.registry = registry or ProgressRegistry()
        self._start_lock = threading.Lock()

    def start(self, market: MarketData, actor: audit.Actor, llm: LlmClient | None) -> tuple[RunSnapshot, bool]:
        """Start a run and return (its snapshot, True); with a run already in flight, return (that run's snapshot, False)."""
        with self._start_lock:
            current = self.registry.in_flight()
            if current is not None:
                return current, False
            with self._session_factory() as db:
                run = open_run(db, market, actor)
                db.commit()
            reporter = SnapshotReporter(self.registry, run)  # in flight from here on
            try:
                threading.Thread(
                    target=self._run, args=(run.id, reporter, market, actor, llm), name=f"analysis-run-{run.id}", daemon=True,
                ).start()
            except BaseException:
                self._finish(run.id, reporter)
                raise
            return reporter.snapshot.model_copy(deep=True), True

    def in_flight(self) -> RunSnapshot | None:
        return self.registry.in_flight()

    def snapshot(self, db: Session, run_id: int) -> RunSnapshot | None:
        latest = self.latest(db, run_id)
        return latest[0] if latest else None

    def latest(self, db: Session, run_id: int) -> tuple[RunSnapshot, int] | None:
        """The run's snapshot with its sequence number: from the registry while it holds the run, otherwise from the
        run row with sequence 0 (a row only changes once more, when an interrupted run is marked on startup)."""
        latest = self.registry.latest(run_id)
        if latest is not None:
            return latest
        run = db.get(AnalysisRunRow, run_id)
        return (snapshot_from_row(run), 0) if run else None

    def _run(
        self, run_id: int, reporter: SnapshotReporter, market: MarketData, actor: audit.Actor, llm: LlmClient | None,
    ) -> None:
        try:
            with self._session_factory() as db:
                run_analysis(db, market, actor, llm, reporter=reporter, run_id=run_id)
        except Exception:
            # The traceback goes to the log, keyed by run id; the snapshot only carries the failed step's fixed message.
            log.exception("Analysis Run %s: %s failed", run_id, reporter.failed_step_label() or "the run")
        finally:  # whatever ends the run, it must leave flight, or every later start would get 409
            self._finish(run_id, reporter)

    def _finish(self, run_id: int, reporter: SnapshotReporter) -> None:
        outcome, finished_at = reporter.outcome(), _now()
        try:
            with self._session_factory() as db:
                run = db.get_one(AnalysisRunRow, run_id)
                save_outcome(run, outcome, finished_at, reporter.snapshot.steps)
                db.commit()
        except Exception:
            log.exception("Analysis Run %s: could not save its outcome", run_id)
        finally:
            reporter.finish(outcome, finished_at)  # no longer in flight, even if saving failed
