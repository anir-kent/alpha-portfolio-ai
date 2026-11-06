"""Run Steps: the fixed, ordered Run Steps of an Analysis Run, and the reporter the run tells about them (ADR-0005).

Progress is telemetry, not a business fact: nothing here writes to the database or the audit chain.
"""
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Literal, Protocol, get_args

RunStepKey = Literal[
    "load_inputs", "score_portfolios", "record_run", "priority_narratives", "recommendation_narratives",
]


@dataclass(frozen=True)
class RunStep:
    key: RunStepKey
    label: str


RUN_STEPS: tuple[RunStep, ...] = (
    RunStep("load_inputs", "Load inputs"),
    RunStep("score_portfolios", "Score Portfolios"),
    RunStep("record_run", "Record run"),
    RunStep("priority_narratives", "Priority narratives"),
    RunStep("recommendation_narratives", "Recommendation narratives"),
)
RUN_STEP_KEYS: tuple[RunStepKey, ...] = tuple(s.key for s in RUN_STEPS)
assert RUN_STEP_KEYS == get_args(RunStepKey)


class RunStepReporter(Protocol):
    def step_started(self, key: RunStepKey) -> None: ...
    def step_finished(self, key: RunStepKey) -> None: ...
    def step_skipped(self, key: RunStepKey) -> None: ...
    def step_failed(self, key: RunStepKey) -> None: ...
    def portfolios_scored(self, done: int, total: int) -> None: ...


class NullReporter:
    """What the command-line run gets: progress goes nowhere."""

    def step_started(self, key: RunStepKey) -> None: pass
    def step_finished(self, key: RunStepKey) -> None: pass
    def step_skipped(self, key: RunStepKey) -> None: pass
    def step_failed(self, key: RunStepKey) -> None: pass
    def portfolios_scored(self, done: int, total: int) -> None: pass


@contextmanager
def run_step(reporter: RunStepReporter, key: RunStepKey) -> Iterator[None]:
    """Report `key` started, then finished; on an exception, failed with every later step skipped, and re-raise."""
    reporter.step_started(key)
    try:
        yield
    except BaseException:
        reporter.step_failed(key)
        for later in RUN_STEP_KEYS[RUN_STEP_KEYS.index(key) + 1:]:
            reporter.step_skipped(later)
        raise
    reporter.step_finished(key)
