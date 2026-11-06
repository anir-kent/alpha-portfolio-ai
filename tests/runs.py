"""Starting an Analysis Run from a test. Every test that starts a run through the API goes through `run_and_wait`: the run
is started in the background (ADR-0005) and its snapshot is polled until it has an outcome."""
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


def run_and_wait(c: TestClient) -> int:
    """Start an Analysis Run as `c` and return its id once it has finished with its results recorded."""
    r = c.post(RUNS)
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    snap = wait_for_outcome(c, run_id)
    assert snap["outcome"] in ("completed", "completed_with_warnings"), snap
    return run_id
