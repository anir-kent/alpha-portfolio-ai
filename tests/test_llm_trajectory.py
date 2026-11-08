"""Seam: the HTTP API (`/api/audit/verify`, `/api/llm/exchanges/{id}`). An Audit Event anchors an ordered LLM Trajectory
and chain verification proves it complete, unaltered and in order (ADR-0004 as amended by ADR-0010). The Trajectory
is built in the test through capture over a scripted Model; no network."""

import hashlib
import json

import httpx
from sqlalchemy import select, text

from app import audit
from app.db import AuditEventRow, LlmExchangeRow
from app.exchanges import ModelLlm, exchange_digest
from app.llm import LlmError, LlmRequest, LlmResponse, exchange_ref
from tests.scripted import ScriptedModel, ScriptedRequest


def echo(request: ScriptedRequest) -> dict | httpx.ConnectError:
    """Answers every request with its own user text, or fails as an unreachable provider does when the text says so."""
    if request.user_prompt == "fail":
        return httpx.ConnectError("provider unavailable")
    return {"echo": request.user_prompt}


def ask(llm, user: str) -> LlmResponse | LlmError:
    try:
        return llm.complete(LlmRequest("assistant_answer", "assistant_answer@v1", "system", user, {"type": "object"}))
    except LlmError as e:
        return e


def anchor(app, outcomes) -> int:
    """Write an Audit Event anchoring the given outcomes as its Trajectory; returns the event id."""
    with app.state.session_factory() as db:
        return audit.record(db, "assistant.answered", audit.Actor.system("t"), {"seq": 1, **exchange_ref(outcomes)})


def capture(app) -> ModelLlm:
    return ModelLlm(ScriptedModel(then=echo, model_name="echo-1"), app.state.session_factory, mode="recorded")


def trajectory_of_three(app) -> tuple[int, list[int | None]]:
    steps = capture(app).trajectory()
    outcomes = [ask(steps, "look up the queue"), ask(steps, "look up the portfolio"), ask(steps, "answer")]
    return anchor(app, outcomes), [o.exchange_id for o in outcomes]


def tamper(app, sql, **params):
    with app.state.session_factory() as db:
        db.execute(text(sql), params)
        db.commit()


def verify(login) -> dict:
    return login("auditor").get("/api/audit/verify").json()


def payload_of(app, event_id) -> dict:
    with app.state.session_factory() as db:
        return json.loads(db.get(AuditEventRow, event_id).payload_json)


def test_a_trajectory_of_three_is_anchored_in_order_and_verifies(app, login):
    event_id, ids = trajectory_of_three(app)
    anchored = payload_of(app, event_id)["exchanges"]
    assert [a["exchange_id"] for a in anchored] == ids
    auditor = login("auditor")
    exchanges = [auditor.get(f"/api/llm/exchanges/{i}").json() for i in ids]
    assert [a["exchange_hash"] for a in anchored] == [ex["hash"] for ex in exchanges]
    assert [ex["trajectory_position"] for ex in exchanges] == [0, 1, 2]
    assert len({ex["trajectory_id"] for ex in exchanges}) == 1 and exchanges[0]["trajectory_id"]
    assert verify(login) == {
        "valid": True,
        "checked": 1,
        "first_broken_id": None,
        "reason": None,
        "exchanges_checked": 3,
        "first_broken_exchange_id": None,
    }


def test_a_single_call_is_a_trajectory_of_one_anchored_as_a_list_of_one(app, login):
    response = ask(capture(app), "answer")
    event_id = anchor(app, response)
    assert payload_of(app, event_id)["exchanges"] == [
        {"exchange_id": response.exchange_id, "exchange_hash": response.exchange_hash}
    ]
    ex = login("auditor").get(f"/api/llm/exchanges/{response.exchange_id}").json()
    assert ex["trajectory_position"] == 0 and ex["trajectory_id"]
    assert verify(login)["valid"] is True


def test_a_failed_request_is_anchored_in_its_trajectory_like_any_other(app, login):
    steps = capture(app).trajectory()
    outcomes = [ask(steps, "look up the queue"), ask(steps, "fail")]
    assert isinstance(outcomes[1], LlmError)
    event_id = anchor(app, outcomes)
    assert [a["exchange_id"] for a in payload_of(app, event_id)["exchanges"]] == [o.exchange_id for o in outcomes]
    assert verify(login)["valid"] is True and verify(login)["exchanges_checked"] == 2


def test_editing_one_exchange_of_a_trajectory_names_that_exchange(app, login):
    event_id, ids = trajectory_of_three(app)
    tamper(app, "update llm_exchanges set raw_reply = 'edited' where id = :i", i=ids[1])
    body = verify(login)
    assert (body["valid"], body["first_broken_id"], body["first_broken_exchange_id"]) == (False, event_id, ids[1])
    assert "altered" in body["reason"]


def test_editing_the_only_exchange_of_a_trajectory_of_one_is_caught(app, login):
    response = ask(capture(app), "answer")
    event_id = anchor(app, response)
    tamper(app, "update llm_exchanges set user_prompt = 'edited' where id = :i", i=response.exchange_id)
    body = verify(login)
    assert (body["first_broken_id"], body["first_broken_exchange_id"]) == (event_id, response.exchange_id)


def test_swapping_two_positions_is_caught_even_when_the_exchange_hashes_are_recomputed(app, login):
    event_id, ids = trajectory_of_three(app)
    with app.state.session_factory() as db:
        first, second = db.get(LlmExchangeRow, ids[0]), db.get(LlmExchangeRow, ids[1])
        first.trajectory_position, second.trajectory_position = second.trajectory_position, first.trajectory_position
        first.hash, second.hash = exchange_digest(first), exchange_digest(second)
        db.commit()
    body = verify(login)
    assert (body["valid"], body["first_broken_id"], body["first_broken_exchange_id"]) == (False, event_id, ids[0])


def test_deleting_the_middle_exchange_reports_it_missing(app, login):
    event_id, ids = trajectory_of_three(app)
    tamper(app, "delete from llm_exchanges where id = :i", i=ids[1])
    body = verify(login)
    assert (body["valid"], body["first_broken_id"], body["first_broken_exchange_id"]) == (False, event_id, ids[1])
    assert "missing" in body["reason"]


def test_an_event_that_anchors_its_trajectory_out_of_order_is_a_break(app, login):
    steps = capture(app).trajectory()
    first, second = ask(steps, "look up the queue"), ask(steps, "answer")
    event_id = anchor(app, [second, first])  # every hash matches, but the list contradicts the recorded positions
    body = verify(login)
    assert (body["valid"], body["first_broken_id"], body["first_broken_exchange_id"]) == (
        False,
        event_id,
        second.exchange_id,
    )
    assert "order" in body["reason"]


def test_an_event_that_anchors_exchanges_from_two_trajectories_is_a_break(app, login):
    own, other = capture(app).trajectory(), capture(app).trajectory()
    first, stray = ask(own, "look up the queue"), ask(other, "look up the portfolio")
    event_id = anchor(app, [first, stray])
    body = verify(login)
    assert (body["first_broken_id"], body["first_broken_exchange_id"]) == (event_id, stray.exchange_id)
    assert "Trajectory" in body["reason"]


def test_an_event_that_leaves_part_of_its_trajectory_unanchored_is_a_break(app, login):
    steps = capture(app).trajectory()
    outcomes = [ask(steps, "look up the queue"), ask(steps, "look up the portfolio"), ask(steps, "answer")]
    event_id = anchor(app, outcomes[:2])
    body = verify(login)
    assert (body["first_broken_id"], body["first_broken_exchange_id"]) == (event_id, outcomes[2].exchange_id)
    assert "not anchored" in body["reason"]


def test_legacy_single_reference_events_and_unreferenced_events_still_verify(app, login):
    """Rows and events written before Trajectories existed: no trajectory id or position, a single id and hash."""
    with app.state.session_factory() as db:
        legacy = LlmExchangeRow(
            created_at="2026-01-01T00:00:00.000000Z",
            task="insight_extraction",
            prompt_version="insight_extraction@v1",
            model="m",
            mode="recorded",
            system_text="s",
            user_prompt="u",
            reply_schema_json="{}",
            outcome="ok",
            hash="",
        )
        legacy.hash = exchange_digest(legacy)
        db.add(legacy)
        db.commit()
        audit.record(
            db, "insight_extracted", audit.Actor.system("t"), {"exchange_id": legacy.id, "exchange_hash": legacy.hash}
        )
        audit.record(db, "memo_generated", audit.Actor.system("t"), {"status": "complete"})
        legacy_id = legacy.id
    trajectory_of_three(app)
    assert login("auditor").get(f"/api/llm/exchanges/{legacy_id}").json()["trajectory_id"] is None
    body = verify(login)
    assert (body["valid"], body["checked"], body["exchanges_checked"]) == (True, 3, 4)

    tamper(app, "update llm_exchanges set user_prompt = 'edited' where id = :i", i=legacy_id)
    assert verify(login)["first_broken_exchange_id"] == legacy_id


def test_trajectory_columns_are_added_to_an_existing_database_whose_exchanges_still_verify(settings):
    import sqlite3

    from app.main import create_app

    app = create_app(settings)
    path = settings.database_url.removeprefix("sqlite:///")
    con = sqlite3.connect(path)  # rebuild the table as it was before Trajectories: no trajectory id, no position
    con.execute("DROP TABLE llm_exchanges")
    con.execute(
        "CREATE TABLE llm_exchanges (id INTEGER PRIMARY KEY AUTOINCREMENT, created_at VARCHAR, task VARCHAR,"
        " prompt_version VARCHAR, model VARCHAR, mode VARCHAR, endpoint_host VARCHAR, system_text TEXT,"
        " user_prompt TEXT, reply_schema_json TEXT, messages_json TEXT, raw_reply TEXT, parsed_content_json TEXT,"
        " usage_json TEXT, latency_ms INTEGER, outcome VARCHAR, error TEXT, hash VARCHAR)"
    )
    # A row as the old capture wrote it, hashed over the old content fields only (sha256 of the canonical list).
    old_content: list[object] = ["2026-01-01T00:00:00.000000Z", "t", "p@v1", "m", "recorded", None, "s", "u", {}]
    old_content += [None, None, {"ok": True}, None, None, "ok", None]
    old_hash = hashlib.sha256(json.dumps(old_content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    con.execute(
        "INSERT INTO llm_exchanges (created_at, task, prompt_version, model, mode, system_text, user_prompt,"
        " reply_schema_json, parsed_content_json, outcome, hash) VALUES"
        " ('2026-01-01T00:00:00.000000Z', 't', 'p@v1', 'm', 'recorded', 's', 'u', '{}', '{\"ok\":true}', 'ok', ?)",
        (old_hash,),
    )
    con.commit()
    con.close()

    for _ in range(2):  # the migration is idempotent: a second start changes nothing
        app = create_app(settings)
    with app.state.session_factory() as db:
        columns = {row[1] for row in db.execute(text("PRAGMA table_info(llm_exchanges)"))}
        assert {"trajectory_id", "trajectory_position"} <= columns
        [row] = db.scalars(select(LlmExchangeRow)).all()
        assert (row.trajectory_id, row.trajectory_position) == (None, None)
        audit.record(
            db, "insight_extracted", audit.Actor.system("t"), {"exchange_id": row.id, "exchange_hash": old_hash}
        )
        assert audit.verify(db).valid
