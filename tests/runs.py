"""Starting an Analysis Run from a test. Every test that starts a run through the API goes through `start_and_wait` (any
outcome) or `run_and_wait` (results recorded): the run is started in the background (ADR-0005) and its snapshot is
polled until it has an outcome."""

import time

from fastapi.testclient import TestClient

RUNS = "/api/analysis/runs"


def wait_for_outcome(c: TestClient, run_id: int, timeout: float = 60) -> dict:
    """Poll the run's snapshot until it has an outcome, and return that final snapshot."""
    deadline = time.monotonic() + timeout
    while True:
        r = c.get(f"{RUNS}/{run_id}")
        assert r.status_code == 200, r.text
        snap = r.json()
        if snap["outcome"] is not None:
            return snap
        assert time.monotonic() < deadline, f"run {run_id} has no outcome after {timeout}s: {snap}"
        time.sleep(0.02)


def start_and_wait(c: TestClient, timeout: float = 60) -> dict:
    """Start an Analysis Run as `c` and return its final snapshot, whatever its outcome."""
    r = c.post(RUNS)
    assert r.status_code == 202, r.text
    return wait_for_outcome(c, r.json()["run_id"], timeout)


def run_and_wait(c: TestClient, timeout: float = 60) -> int:
    """Start an Analysis Run as `c` and return its id once it has finished with its results recorded. Live LLM steps
    (when recording) need a far longer `timeout` than replay."""
    snap = start_and_wait(c, timeout)
    assert snap["outcome"] in ("completed", "completed_with_warnings"), snap
    return snap["run_id"]
