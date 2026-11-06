"""Starting an Analysis Run from a test. Every test that starts a run through the API goes through `run_and_wait`, so
the run moving to the background (ADR-0005) changes only this helper."""
from fastapi.testclient import TestClient

RUNS = "/api/analysis/runs"


def run_and_wait(c: TestClient) -> int:
    """Start an Analysis Run as `c` and return its id once it has finished."""
    r = c.post(RUNS)
    assert r.status_code == 200, r.text
    return r.json()["run_id"]
