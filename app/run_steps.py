"""Run Steps: the fixed, ordered Run Steps of an Analysis Run, and the reporter the run tells about them (ADR-0005).

Progress is telemetry, not a business fact: nothing here writes to the database or the audit chain.
"""
from collections.abc import Callable, Iterator, Sequence
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
    failure_message: str  # what a failed step shows: fixed and safe; the exception itself only goes to the server log


AI_STEP_FAILED = "Narrative unavailable (AI step failed; scores are unaffected)."  # the Queue's wording for a failed narrative

RUN_STEPS: tuple[RunStep, ...] = (
    RunStep("load_inputs", "Load inputs", "Loading inputs failed"),
    RunStep("score_portfolios", "Score Portfolios", "Scoring failed"),
    RunStep("record_run", "Record run", "Recording the run failed"),
    RunStep("priority_narratives", "Priority narratives", AI_STEP_FAILED),
    RunStep("recommendation_narratives", "Recommendation narratives", AI_STEP_FAILED),
)
RUN_STEP_KEYS: tuple[RunStepKey, ...] = tuple(s.key for s in RUN_STEPS)
assert RUN_STEP_KEYS == get_args(RunStepKey)
AI_STEP_KEYS: tuple[RunStepKey, ...] = ("priority_narratives", "recommendation_narratives")


def step(key: RunStepKey) -> RunStep:
    return RUN_STEPS[RUN_STEP_KEYS.index(key)]


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
    """A scoring step: report `key` started, then finished; on an exception, failed with every later step skipped, and
    re-raise. The AI steps run after the commit and do not stop each other (`run_ai_steps`)."""
    reporter.step_started(key)
    try:
        yield
    except BaseException:
        reporter.step_failed(key)
        for later in RUN_STEP_KEYS[RUN_STEP_KEYS.index(key) + 1:]:
            reporter.step_skipped(later)
        raise
    reporter.step_finished(key)


def run_ai_steps(reporter: RunStepReporter, steps: Sequence[tuple[RunStepKey, Callable[[], int]]], recover: Callable[[], None]) -> None:
    """Run each AI step in turn; each returns how many of its items failed. A step is failed if any item failed or it
    raised. One failing never stops the next: after an exception, `recover` readies the session for it, and the first
    exception is re-raised once every step has run, so the caller still sees (and logs) it."""
    error: Exception | None = None
    for key, generate in steps:
        reporter.step_started(key)
        try:
            failed = generate()
        except Exception as e:
            recover()
            reporter.step_failed(key)
            error = error or e
            continue
        if failed:
            reporter.step_failed(key)
        else:
            reporter.step_finished(key)
    if error is not None:
        raise error
