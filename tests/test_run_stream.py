"""Seam: the HTTP API. The live Run Step stream, `GET /analysis/runs/{id}/events` (ADR-0005): each event is the run's full
snapshot, its id the run's sequence number. Timing is controlled only through the LLM the app is given."""
import threading
import time

from tests.runs import RUNS, run_and_wait, wait_for_outcome
from tests.sse import data_events, parse_events
from tests.test_analysis_runs import advisor, frozen, outcomes  # noqa: F401  (fixtures)
from tests.test_queue import seeded  # noqa: F401  (fixture)


def read_run_stream(app, c, run_id, last_event_id=None, seconds=30.0, while_open=None):
    """Connect to the run's stream and read until the server closes it (at the latest after `seconds`).
    Returns its `progress` events as (id, snapshot) in order, and how long the stream stayed open."""
    app.state.settings.llm_stream_poll_seconds = 0.05
    app.state.settings.llm_stream_max_seconds = seconds
    if while_open:
        threading.Timer(0.3, while_open).start()
    headers = {"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    began = time.monotonic()
    r = c.get(f"{RUNS}/{run_id}/events", headers=headers)
    elapsed = time.monotonic() - began
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    assert {e.get("event") for e in parse_events(r.text)} <= {"progress"}
    return data_events(r.text), elapsed


def test_connecting_to_a_finished_run_sends_its_final_snapshot_and_closes(app, advisor):
    run_id = run_and_wait(advisor)
    events, elapsed = read_run_stream(app, advisor, run_id)
    assert len(events) == 1
    snap = events[0][1]
    assert snap == advisor.get(f"{RUNS}/{run_id}").json()
    assert snap["outcome"] == "completed" and outcomes(snap) == ["done"] * 5
    assert elapsed < 5


def test_watching_a_run_shows_the_frozen_mid_run_state_then_the_outcome_in_sequence_order_and_closes(app, advisor, frozen):
    run_id, llm = frozen
    events, elapsed = read_run_stream(app, advisor, run_id, while_open=llm.release.set)
    ids = [i for i, _ in events]
    assert ids == sorted(set(ids)) and len(ids) >= 2  # one event per change, never repeated
    first, last = events[0][1], events[-1][1]
    assert outcomes(first) == ["done", "running", "pending", "pending", "pending"] and first["outcome"] is None
    scoring = first["steps"][1]
    assert scoring["total"] == 25 and 0 <= scoring["done"] < 25
    assert last["outcome"] == "completed" and outcomes(last) == ["done"] * 5
    assert all(s["outcome"] is None for _, s in events[:-1])  # the stream ends with the first snapshot that has an outcome
    assert last == wait_for_outcome(advisor, run_id)
    assert elapsed < 25  # closed by the outcome, not by the stream's maximum duration


def test_a_reconnect_with_the_current_sequence_number_gets_no_unchanged_snapshot(app, advisor, frozen):
    run_id, llm = frozen
    events, _ = read_run_stream(app, advisor, run_id, seconds=0.3)  # the stream's maximum duration ends it mid-run
    assert len(events) == 1 and events[0][1]["outcome"] is None
    seq = events[0][0]
    assert read_run_stream(app, advisor, run_id, last_event_id=seq, seconds=0.3)[0] == []  # nothing changed meanwhile
    llm.release.set()
    resumed, _ = read_run_stream(app, advisor, run_id, last_event_id=seq)
    assert resumed and all(i > seq for i, _ in resumed) and resumed[-1][1]["outcome"] == "completed"
    final_seq = resumed[-1][0]
    assert read_run_stream(app, advisor, run_id, last_event_id=final_seq)[0] == []  # already has the final snapshot
    assert read_run_stream(app, advisor, run_id, last_event_id=seq)[0] == [resumed[-1]]  # behind: only the latest


def test_a_last_event_id_that_is_not_a_sequence_number_is_ignored(app, advisor):
    run_id = run_and_wait(advisor)
    assert len(read_run_stream(app, advisor, run_id, last_event_id="not-a-number")[0]) == 1


def test_an_older_run_no_longer_held_in_memory_is_streamed_from_its_saved_result(app, advisor):
    first = run_and_wait(advisor)
    run_and_wait(advisor)
    run_and_wait(advisor)
    events, _ = read_run_stream(app, advisor, first)
    assert [s for _, s in events] == [advisor.get(f"{RUNS}/{first}").json()]


def test_keepalives_are_sent_while_nothing_changes(app, advisor, frozen, monkeypatch):
    from app import sse
    monkeypatch.setattr(sse, "KEEPALIVE_SECONDS", 0.1)  # the streams' shared keepalive interval, shortened
    run_id, _ = frozen
    app.state.settings.llm_stream_poll_seconds = 0.05
    app.state.settings.llm_stream_max_seconds = 0.5
    r = advisor.get(f"{RUNS}/{run_id}/events")
    assert r.text.count(": keepalive") >= 2


def test_streaming_an_unknown_run_is_404(app, advisor):
    assert advisor.get(f"{RUNS}/9999/events").status_code == 404


def test_the_stream_needs_a_session(client):
    assert client.get(f"{RUNS}/1/events").status_code == 401
