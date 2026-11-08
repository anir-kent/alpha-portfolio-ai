"""Seam: the HTTP API. Exchange list, detail and live stream for `llm:read` roles (ADR-0004). No network."""

import json
import threading
from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app import audit
from app.db import AuditEventRow, GroundingResultRow, LlmExchangeRow
from app.exchanges import exchange_digest
from tests.conftest import ROLES
from tests.sse import data_events

READERS = ("auditor", "compliance_officer", "platform_owner")
BULK = ("system_text", "user_prompt", "reply_schema", "messages", "raw_reply", "parsed_content")


def add_exchange(
    app,
    *,
    ts,
    task="insight_extraction",
    version="insight_extraction@v1",
    mode="recorded",
    outcome="ok",
    usage=None,
    latency=None,
    event: dict | None = None,
    event_type="memo_generated",
    **scope,
) -> int:
    """Store one Exchange; if `event` is given, also an Audit Event referencing it (payload extended with `event`)."""
    with app.state.session_factory() as db:
        row = LlmExchangeRow(
            created_at=ts,
            task=task,
            prompt_version=version,
            model="m",
            mode=mode,
            endpoint_host=None,
            system_text="SYSTEM " * 50,
            user_prompt="USER " * 50,
            reply_schema_json="{}",
            raw_reply="RAW",
            usage_json=json.dumps(usage) if usage else None,
            latency_ms=latency,
            outcome=outcome,
            error="boom" if outcome == "error" else None,
            hash="",
        )
        row.hash = exchange_digest(row)
        db.add(row)
        db.commit()
        if event is not None:
            audit.record(
                db,
                event_type,
                audit.Actor.system("t"),
                {**event, "exchange_id": row.id, "exchange_hash": row.hash},
                **scope,
            )
        return row.id


def test_list_is_newest_first_summary_rows_with_the_linked_portfolio_and_pagination(app, login):
    a = add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    b = add_exchange(
        app,
        ts="2026-01-02T00:00:00.000000Z",
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        latency=120,
        event={},
        portfolio_id="P-1",
        client_id="C-1",
        recommendation_id="7",
    )
    c = add_exchange(app, ts="2026-01-03T00:00:00.000000Z")

    r = login("auditor").get("/api/llm/exchanges")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 3 and [i["id"] for i in body["items"]] == [c, b, a]
    row = body["items"][1]
    assert not set(BULK) & set(row)  # summary rows only: no bulk text
    assert (row["portfolio_id"], row["recommendation_id"]) == ("P-1", "7")
    assert (row["latency_ms"], row["usage"]["total_tokens"], row["task"], row["mode"], row["outcome"]) == (
        120,
        15,
        "insight_extraction",
        "recorded",
        "ok",
    )
    assert body["items"][0]["portfolio_id"] is None and body["items"][0]["recommendation_id"] is None

    page = login("auditor").get("/api/llm/exchanges", params={"limit": 1, "offset": 1}).json()
    assert page["total"] == 3 and [i["id"] for i in page["items"]] == [b]


def test_failed_exchange_rows_carry_a_bounded_error_summary_and_ok_rows_none(app, login):
    ok = add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    bad = add_exchange(app, ts="2026-01-02T00:00:00.000000Z", outcome="error")
    with app.state.session_factory() as db:
        db.get(LlmExchangeRow, bad).error = "x" * 1000
        db.commit()
    by_id = {i["id"]: i for i in login("auditor").get("/api/llm/exchanges").json()["items"]}
    assert by_id[ok]["error"] is None
    assert (
        by_id[bad]["error"].startswith("xxx") and len(by_id[bad]["error"]) == 200
    )  # bounded: a summary, not bulk text


def ids(c, **params):
    r = c.get("/api/llm/exchanges", params=params)
    assert r.status_code == 200, r.text
    return [i["id"] for i in r.json()["items"]]


def test_list_filters_combine_by_task_version_mode_outcome_and_date_range(app, login):
    add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    b = add_exchange(
        app, ts="2026-01-02T00:00:00.000000Z", task="research_tilt", version="research_tilt@v2", mode="live"
    )
    c = add_exchange(
        app, ts="2026-01-03T00:00:00.000000Z", task="research_tilt", version="research_tilt@v1", outcome="error"
    )
    d = add_exchange(
        app,
        ts="2026-01-04T00:00:00.000000Z",
        task="research_tilt",
        version="research_tilt@v2",
        mode="live",
        outcome="error",
    )
    auditor = login("auditor")
    assert ids(auditor, task="research_tilt") == [d, c, b]
    assert ids(auditor, prompt_version="research_tilt@v2") == [d, b]
    assert ids(auditor, mode="live") == [d, b]
    assert ids(auditor, outcome="error") == [d, c]
    assert ids(auditor, task="research_tilt", mode="live", outcome="error") == [d]
    assert ids(auditor, date_from="2026-01-02T00:00:00Z", date_to="2026-01-03T12:00:00Z") == [c, b]
    assert ids(auditor, date_from="2026-01-02T00:00:00Z", outcome="ok") == [b]
    assert ids(auditor, task="nothing") == []
    assert login("auditor").get("/api/llm/exchanges", params={"mode": "bogus"}).status_code == 422


def add_grounding(app, check_id, grounded_flags):
    with app.state.session_factory() as db:
        for i, g in enumerate(grounded_flags):
            db.add(
                GroundingResultRow(
                    check_id=check_id,
                    recommendation_id=None,
                    run_id=None,
                    client_id="C-1",
                    claim_index=i,
                    text=f"claim {i}",
                    asset=None,
                    citations_json="[]",
                    grounded=g,
                    issues_json=json.dumps([] if g else [{"code": "number_mismatch", "message": "figure differs"}]),
                    created_at="2026-01-01T00:00:00.000000Z",
                )
            )
        db.commit()


def test_detail_has_the_full_record_the_referencing_events_and_the_grounding_verdict(app, login):
    add_grounding(app, "GRD-abc", [True, True, False])
    xid = add_exchange(
        app,
        ts="2026-01-01T00:00:00.000000Z",
        task="recommendation_narrative",
        event={"status": "complete", "check_id": "GRD-abc"},
        recommendation_id="7",
        portfolio_id="P-1",
    )
    r = login("compliance_officer").get(f"/api/llm/exchanges/{xid}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["system_text"].startswith("SYSTEM") and body["raw_reply"] == "RAW"
    [used] = body["used_by"]
    assert (used["type"], used["recommendation_id"], used["portfolio_id"], used["payload"]["check_id"]) == (
        "memo_generated",
        "7",
        "P-1",
        "GRD-abc",
    )
    [verdict] = body["grounding"]
    assert verdict["check_id"] == "GRD-abc" and verdict["summary"] == {"total": 3, "grounded": 2, "ungrounded": 1}
    assert [(c["index"], c["grounded"]) for c in verdict["claims"]] == [(0, True), (1, True), (2, False)]
    assert [i["code"] for i in verdict["claims"][2]["issues"]] == ["number_mismatch"]


def test_detail_of_an_exchange_no_event_references_has_empty_lineage(app, login):
    xid = add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    body = login("auditor").get(f"/api/llm/exchanges/{xid}").json()
    assert body["used_by"] == [] and body["grounding"] == []
    assert login("auditor").get("/api/llm/exchanges/9999").status_code == 404


# --- live stream ------------------------------------------------------------------------------------------------


def read_stream(app, c, last_event_id=None, seconds=0.6, while_open=None):
    """Connect, let the stream run for `seconds`, and return its (id, summary) events in order."""
    app.state.settings.llm_stream_poll_seconds = 0.05
    app.state.settings.llm_stream_max_seconds = seconds
    if while_open:
        threading.Timer(seconds / 3, while_open).start()
    r = c.get(
        "/api/llm/exchanges/stream", headers={"Last-Event-ID": str(last_event_id)} if last_event_id is not None else {}
    )
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")
    return data_events(r.text)


def test_stream_resumes_after_last_event_id_in_id_order_without_gaps_or_repeats(app, login):
    first, second, third = (add_exchange(app, ts=f"2026-01-0{i}T00:00:00.000000Z") for i in (1, 2, 3))
    auditor = login("auditor")
    events = read_stream(app, auditor, last_event_id=first)
    assert [i for i, _ in events] == [second, third]
    assert [d["id"] for _, d in events] == [second, third]
    assert not set(BULK) & set(events[0][1])  # summary rows, like the list

    fourth = add_exchange(app, ts="2026-01-04T00:00:00.000000Z")
    assert [i for i, _ in read_stream(app, auditor, last_event_id=third)] == [
        fourth
    ]  # reconnect: nothing missed, nothing repeated
    assert read_stream(app, auditor, last_event_id=fourth) == []


def test_stream_without_a_resume_header_pushes_only_exchanges_that_complete_while_open(app, login):
    add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    new = []
    events = read_stream(
        app,
        login("auditor"),
        while_open=lambda: new.append(
            add_exchange(app, ts="2026-01-02T00:00:00.000000Z", event={}, portfolio_id="P-9")
        ),
    )
    assert [i for i, _ in events] == new
    assert events[0][1]["portfolio_id"] == "P-9"


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(
    "path",
    [
        "/api/llm/exchanges",
        "/api/llm/exchanges?group=trajectory",
        "/api/llm/exchanges?trajectory_id=abc",
        "/api/llm/exchanges/1",
        "/api/llm/exchanges/stream",
    ],
)
def test_every_exchange_endpoint_is_gated_on_llm_read_and_refusals_are_audited(app, login, role, path):
    add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    app.state.settings.llm_stream_max_seconds = 0.1
    r = login(role).get(path)
    if role in READERS:
        assert r.status_code == 200, r.text
        return
    assert r.status_code == 403
    with app.state.session_factory() as db:
        denied = db.scalars(select(AuditEventRow).where(AuditEventRow.type == "access_denied")).all()
    assert any(
        json.loads(d.payload_json) == {"permission": "llm:read", "method": "GET", "path": path.split("?")[0]}
        and d.actor_role == role
        for d in denied
    )


def test_stream_needs_a_session(client):
    assert client.get("/api/llm/exchanges/stream").status_code == 401


def now_ts():
    from app.audit import format_ts

    return format_ts(datetime.now(UTC))


def test_stream_waits_for_the_referencing_event_so_the_linked_portfolio_is_not_lost(app, login):
    """The Exchange is stored just before the event that references it; the stream must not send it link-less."""
    with app.state.session_factory() as db:
        row = LlmExchangeRow(
            created_at=now_ts(),
            task="t",
            prompt_version="p@v1",
            model="m",
            mode="live",
            system_text="s",
            user_prompt="u",
            reply_schema_json="{}",
            outcome="ok",
            hash="",
        )
        row.hash = exchange_digest(row)
        db.add(row)
        db.commit()
        xid, xhash = row.id, row.hash
    app.state.settings.llm_stream_poll_seconds = 0.05

    def reference():
        with app.state.session_factory() as db:
            audit.record(
                db,
                "memo_generated",
                audit.Actor.system("t"),
                {"exchange_id": xid, "exchange_hash": xhash},
                portfolio_id="P-5",
            )

    events = read_stream(app, login("auditor"), last_event_id=xid - 1, seconds=1.2, while_open=reference)
    assert [(i, d["portfolio_id"]) for i, d in events] == [(xid, "P-5")]


def test_stream_still_delivers_a_fresh_exchange_that_no_event_references(app, login):
    with app.state.session_factory() as db:
        row = LlmExchangeRow(
            created_at=now_ts(),
            task="t",
            prompt_version="p@v1",
            model="m",
            mode="live",
            system_text="s",
            user_prompt="u",
            reply_schema_json="{}",
            outcome="error",
            error="x",
            hash="",
        )
        row.hash = exchange_digest(row)
        db.add(row)
        db.commit()
        xid = row.id
    events = read_stream(app, login("auditor"), last_event_id=xid - 1, seconds=3.0)
    assert [(i, d["portfolio_id"]) for i, d in events] == [(xid, None)]


def test_stream_ignores_a_last_event_id_that_is_not_an_id_and_starts_at_the_tail(app, login):
    add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    app.state.settings.llm_stream_poll_seconds = 0.05
    app.state.settings.llm_stream_max_seconds = 0.2
    r = login("auditor").get("/api/llm/exchanges/stream", headers={"Last-Event-ID": "not-an-id"})
    assert r.status_code == 200 and "event: exchange" not in r.text


def test_stream_opens_with_its_cursor_so_a_client_that_saw_nothing_still_resumes(app, login):
    last = add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    app.state.settings.llm_stream_poll_seconds = 0.05
    app.state.settings.llm_stream_max_seconds = 0.2
    r = login("auditor").get("/api/llm/exchanges/stream")
    assert r.text.startswith(f"id: {last}\n\n")


# --- Trajectories (ADR-0010) ---------------------------------------------------------------------------------------


def trajectory(app, *users: str) -> list[int]:
    """One LLM Trajectory of `len(users)` requests through capture over a scripted Model; returns its Exchange ids. A
    request whose text is "fail" fails as an unreachable provider does and is stored as an error Exchange."""
    import httpx

    from app.exchanges import ModelLlm
    from app.llm import LlmError, LlmRequest, LlmResponse
    from tests.scripted import ScriptedModel

    def echo(request):
        return (
            httpx.ConnectError("provider unavailable")
            if request.user_prompt == "fail"
            else {"echo": request.user_prompt}
        )

    steps = ModelLlm(ScriptedModel(then=echo), app.state.session_factory, mode="recorded").trajectory()
    ids = []
    for user in users:
        outcome: LlmResponse | LlmError
        try:
            outcome = steps.complete(
                LlmRequest("assistant_answer", "assistant_answer@v5", "system", user, {"type": "object"})
            )
        except LlmError as e:
            outcome = e
        assert outcome.exchange_id is not None
        ids.append(outcome.exchange_id)
    return ids


def test_grouped_list_pages_by_trajectory_with_its_steps_in_position_order(app, login):
    single = add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    first = trajectory(app, "look up", "answer")
    second = trajectory(app, "look up", "look up again", "answer")
    auditor = login("auditor")

    body = auditor.get("/api/llm/exchanges", params={"group": "trajectory", "limit": 1}).json()
    assert body["total"] == 3  # Trajectories, not Exchanges
    assert [x["id"] for x in body["items"]] == second  # newest Trajectory first, its steps in position order
    assert [x["trajectory_position"] for x in body["items"]] == [0, 1, 2]
    assert {x["trajectory_length"] for x in body["items"]} == {3}

    rest = auditor.get("/api/llm/exchanges", params={"group": "trajectory", "limit": 5, "offset": 1}).json()
    assert [x["id"] for x in rest["items"]] == [*first, single]
    assert rest["items"][-1]["trajectory_id"] is None and rest["items"][-1]["trajectory_length"] == 1


def test_a_trajectory_filter_returns_just_that_trajectory_and_the_other_filters_still_apply(app, login):
    add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    ids = trajectory(app, "look up", "answer")
    trajectory(app, "another")
    auditor = login("auditor")
    tid = auditor.get(f"/api/llm/exchanges/{ids[0]}").json()["trajectory_id"]

    body = auditor.get("/api/llm/exchanges", params={"trajectory_id": tid}).json()
    assert body["total"] == 2 and sorted(x["id"] for x in body["items"]) == ids
    assert auditor.get("/api/llm/exchanges", params={"trajectory_id": tid, "outcome": "error"}).json()["total"] == 0
    grouped = auditor.get("/api/llm/exchanges", params={"group": "trajectory", "task": "insight_extraction"}).json()
    assert grouped["total"] == 1 and grouped["items"][0]["trajectory_length"] == 1


def test_a_filter_that_matches_part_of_a_trajectory_shows_that_part_with_the_full_length(app, login):
    ids = trajectory(app, "look up", "fail")
    trajectory(app, "answer")
    body = login("auditor").get("/api/llm/exchanges", params={"group": "trajectory", "outcome": "error"}).json()
    assert body["total"] == 1
    assert [(x["id"], x["trajectory_position"], x["trajectory_length"]) for x in body["items"]] == [(ids[1], 1, 2)]


def test_the_drawer_detail_names_the_trajectory_steps_so_an_auditor_can_walk_them(app, login):
    single = add_exchange(app, ts="2026-01-01T00:00:00.000000Z")
    ids = trajectory(app, "look up", "look up again", "answer")
    auditor = login("auditor")
    middle = auditor.get(f"/api/llm/exchanges/{ids[1]}").json()
    assert middle["trajectory_position"] == 1 and middle["trajectory_exchange_ids"] == ids
    assert auditor.get(f"/api/llm/exchanges/{single}").json()["trajectory_exchange_ids"] == [single]
