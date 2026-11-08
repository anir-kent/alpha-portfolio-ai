"""Seam: the HTTP API. Every LLM call made while ingesting a Report is captured as an immutable LLM Exchange that the
insight Audit Event references by id and hash (ADR-0004). Recordings only; no network."""

import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app import audit
from app.db import AuditEventRow
from tests.chat_completions import completion
from tests.conftest import ROLES

FIXTURES = Path(__file__).parent / "fixtures"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def upload(c, name="house_view_demo.txt", content=None):
    content = (FIXTURES / name).read_bytes() if content is None else content
    return c.post("/api/reports", files={"file": (name, content)})


def extraction_event(app, report_id):
    with app.state.session_factory() as db:
        row = db.scalars(
            select(AuditEventRow).where(AuditEventRow.report_id == report_id, AuditEventRow.type == "insight_extracted")
        ).one()
        return json.loads(row.payload_json)


def test_recorded_extraction_is_captured_and_anchored_in_the_audit_event(app, login):
    report = upload(login("research_analyst")).json()
    payload = extraction_event(app, report["id"])
    assert HEX64.match(payload["exchanges"][0]["exchange_hash"])

    r = login("auditor").get(f"/api/llm/exchanges/{payload['exchanges'][0]['exchange_id']}")
    assert r.status_code == 200, r.text
    ex = r.json()
    assert ex["hash"] == payload["exchanges"][0]["exchange_hash"]
    assert (ex["mode"], ex["outcome"], ex["task"]) == ("recorded", "ok", "insight_extraction")
    assert (ex["prompt_version"], ex["model"]) == ("insight_extraction@v1", "claude-sonnet-5-5")
    assert "We are constructive on technology." in ex["user_prompt"]
    assert ex["system_text"] and ex["reply_schema"]["properties"]["insights"]
    assert {i["subject"] for i in ex["parsed_content"]["insights"]} == {"Information Technology", "Utilities", "equity"}
    with app.state.session_factory() as db:
        assert audit.verify(db).valid


def test_a_call_with_no_recording_is_captured_as_an_error_exchange(app, login):
    r = upload(login("research_analyst"), content=b"A report nobody recorded a reply for.\n")
    assert r.json()["extraction_status"] == "failed" and "No recorded response" in r.json()["extraction_error"]
    payload = extraction_event(app, r.json()["id"])
    assert payload["outcome"] == "failed" and payload["insight_count"] == 0

    ex = login("auditor").get(f"/api/llm/exchanges/{payload['exchanges'][0]['exchange_id']}").json()
    assert (ex["outcome"], ex["mode"]) == ("error", "recorded")
    assert "No recorded response" in ex["error"]
    assert ex["hash"] == payload["exchanges"][0]["exchange_hash"]
    with app.state.session_factory() as db:
        assert audit.verify(db).valid


def test_failing_to_save_the_exchange_fails_the_ai_step_but_not_deterministic_features(app, login):
    with app.state.session_factory() as db:
        db.execute(text("DROP TABLE llm_exchanges"))
        db.commit()
    r = upload(login("research_analyst"))
    assert r.status_code == 201
    assert r.json()["extraction_status"] == "failed" and r.json()["insights"] == []
    payload = extraction_event(app, r.json()["id"])
    assert "exchanges" not in payload and payload["outcome"] == "failed"
    assert login("auditor").get("/api/audit/verify").json()["valid"]
    assert login("platform_owner").get("/api/config").status_code == 200


def test_exchange_table_is_created_on_an_existing_database(settings):
    import sqlite3

    from app.main import create_app

    create_app(settings)
    con = sqlite3.connect(settings.database_url.removeprefix("sqlite:///"))
    con.execute("DROP TABLE llm_exchanges")
    con.commit()
    con.close()
    app = create_app(settings)  # the schema bootstrap re-creates it, leaving existing tables alone
    with app.state.session_factory() as db:
        assert db.execute(text("SELECT COUNT(*) FROM llm_exchanges")).scalar() == 0


@pytest.mark.parametrize("role", ROLES)
def test_exchange_read_is_limited_to_llm_read_roles_and_refusals_are_audited(app, login, role):
    report = upload(login("research_analyst")).json()
    exchange_id = extraction_event(app, report["id"])["exchanges"][0]["exchange_id"]
    r = login(role).get(f"/api/llm/exchanges/{exchange_id}")
    if role in ("auditor", "compliance_officer", "platform_owner"):
        assert r.status_code == 200
        return
    assert r.status_code == 403
    with app.state.session_factory() as db:
        denied = db.scalars(select(AuditEventRow).where(AuditEventRow.type == "access_denied")).all()
    assert any(json.loads(d.payload_json)["permission"] == "llm:read" and d.actor_role == role for d in denied)


# --- live transport fidelity (ticket 02): a mock transport stands in for the provider; no network ---------------

API_KEY = "sk-live-secret-do-not-store"
GOOD_REPLY = '```json\n{"insights": []}\n```'


@pytest.fixture
def live_app(tmp_path, allow_model_requests):
    """Returns a builder: live-mode app whose provider is `handler`, plus the requests the provider saw."""
    import httpx

    from app.main import create_app
    from app.settings import Settings

    def build(handler):
        seen = []

        def recording(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return handler(request)

        settings = Settings(
            database_url=f"sqlite:///{tmp_path / 'live.db'}",
            seed_user_password="test-only-password",
            market_data_snapshot_path=str(tmp_path / "snapshot.json"),
            llm_mode="live",
            llm_api_key=API_KEY,
            llm_base_url="https://gw.example/v1",
            llm_model="m",
        )
        return create_app(settings, llm_transport=httpx.MockTransport(recording)), seen

    return build


def provider_ok(request):
    return completion(GOOD_REPLY)


def as_role(app, role):
    from fastapi.testclient import TestClient

    c = TestClient(app)
    assert c.post("/api/auth/login", json={"username": role, "password": "test-only-password"}).status_code == 200
    return c


def test_live_exchange_stores_what_crossed_the_wire(live_app):
    app, seen = live_app(provider_ok)
    report = upload(as_role(app, "research_analyst")).json()
    ex = (
        as_role(app, "auditor")
        .get(f"/api/llm/exchanges/{extraction_event(app, report['id'])['exchanges'][0]['exchange_id']}")
        .json()
    )

    sent = json.loads(seen[0].content)["messages"]
    assert ex["messages"] == sent
    assert ex["messages"][0]["content"].startswith(ex["system_text"] + "\n\nJSON schema of the reply:\n")
    assert json.loads(ex["raw_reply"])["choices"][0]["message"]["content"] == GOOD_REPLY  # the reply body as received
    assert ex["usage"] == {"prompt_tokens": 321, "completion_tokens": 45, "total_tokens": 366}
    assert isinstance(ex["latency_ms"], int) and ex["latency_ms"] >= 0
    assert (ex["mode"], ex["outcome"], ex["endpoint_host"], ex["telemetry"]) == ("live", "ok", "gw.example", "measured")
    assert ex["parsed_content"] == {"insights": []}


def exchange_for(app, report):
    return (
        as_role(app, "auditor")
        .get(f"/api/llm/exchanges/{extraction_event(app, report['id'])['exchanges'][0]['exchange_id']}")
        .json()
    )


def test_recorded_exchange_marks_tokens_and_latency_as_replayed_not_zero(app, login):
    report = upload(login("research_analyst")).json()
    ex = exchange_for(app, report)
    assert ex["telemetry"] == "not_available_replayed"
    assert ex["usage"] is None and ex["latency_ms"] is None
    assert ex["messages"] is None and ex["raw_reply"] is None  # nothing crossed a wire on a replay


def test_provider_http_error_is_an_error_exchange_with_status_and_text(live_app):
    import httpx

    app, _ = live_app(lambda r: httpx.Response(503, text="upstream overloaded"))
    report = upload(as_role(app, "research_analyst")).json()
    assert report["extraction_status"] == "failed"
    ex = exchange_for(app, report)
    assert ex["outcome"] == "error" and ex["mode"] == "live"
    assert "HTTP 503" in ex["error"] and "upstream overloaded" in ex["error"]
    assert ex["messages"] and isinstance(ex["latency_ms"], int)  # the request that was sent is still on record
    assert ex["parsed_content"] is None


def test_provider_timeout_is_an_error_exchange_with_the_failure_text(live_app):
    import httpx

    def timeout(request):
        raise httpx.ReadTimeout("read timed out", request=request)

    app, _ = live_app(timeout)
    ex = exchange_for(app, upload(as_role(app, "research_analyst")).json())
    assert ex["outcome"] == "error" and "ReadTimeout" in ex["error"] and "read timed out" in ex["error"]
    assert ex["raw_reply"] is None and ex["messages"]


def test_reply_that_is_not_json_is_an_error_exchange_that_keeps_the_raw_text(live_app):

    prose = "Sure! Here are the insights you asked for, in prose."
    app, _ = live_app(
        lambda r: completion(prose, usage={"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9})
    )
    ex = exchange_for(app, upload(as_role(app, "research_analyst")).json())
    assert ex["outcome"] == "error" and "not valid JSON" in ex["error"]
    assert json.loads(ex["raw_reply"])["choices"][0]["message"]["content"] == prose  # the reply as received
    assert ex["usage"] == {"prompt_tokens": 5, "completion_tokens": 4, "total_tokens": 9}
    assert ex["parsed_content"] is None


def test_api_key_and_headers_never_appear_in_any_exchange_or_response(live_app):
    import httpx

    # A hostile provider that echoes the credential back in its error body must not get it stored either.
    app, seen = live_app(lambda r: httpx.Response(401, text=f"bad credential {r.headers['authorization']}"))
    report = upload(as_role(app, "research_analyst")).json()
    assert seen[0].headers["authorization"] == f"Bearer {API_KEY}"  # it really was sent
    ex = as_role(app, "auditor").get(
        f"/api/llm/exchanges/{extraction_event(app, report['id'])['exchanges'][0]['exchange_id']}"
    )
    with app.state.session_factory() as db:
        stored = " ".join(str(v) for row in db.execute(text("SELECT * FROM llm_exchanges")) for v in row)
        stored += " ".join(r.payload_json for r in db.scalars(select(AuditEventRow)))
    for blob in (ex.text, stored, json.dumps(report)):
        assert API_KEY not in blob and "authorization" not in blob.lower()
    assert ex.json()["outcome"] == "error"

    ok_app, _ = live_app(provider_ok)
    ok = exchange_for(ok_app, upload(as_role(ok_app, "research_analyst")).json())
    assert API_KEY not in json.dumps(ok) and "authorization" not in json.dumps(ok).lower()


def test_reply_with_no_text_content_is_an_error_exchange_not_a_server_error(live_app):

    app, _ = live_app(lambda r: completion(None))
    report = upload(as_role(app, "research_analyst"))
    assert report.status_code == 201 and report.json()["extraction_status"] == "failed"
    ex = exchange_for(app, report.json())
    assert ex["outcome"] == "error" and "not text" in ex["error"]
    assert ex["raw_reply"] is not None and "choices" in ex["raw_reply"]


def test_provider_redirect_is_reported_as_an_http_failure(live_app):
    import httpx

    app, _ = live_app(lambda r: httpx.Response(301, headers={"location": "https://elsewhere.example/"}))
    ex = exchange_for(app, upload(as_role(app, "research_analyst")).json())
    assert ex["outcome"] == "error" and "HTTP 301" in ex["error"]


# --- verification and capture health (ticket 04) -----------------------------------------------------------------


def tamper(app, sql, **params):
    with app.state.session_factory() as db:
        db.execute(text(sql), params)
        db.commit()


def test_verify_also_checks_every_referenced_exchange(app, login):
    upload(login("research_analyst"))
    body = login("auditor").get("/api/audit/verify").json()
    assert body["valid"] is True
    assert body["exchanges_checked"] == 1 and body["first_broken_exchange_id"] is None


def test_verify_names_the_first_event_whose_exchange_was_altered(app, login):
    first = upload(login("research_analyst")).json()
    second = upload(login("research_analyst"), content=b"Another view. We are cautious on energy.\n").json()
    e1, e2 = extraction_event(app, first["id"]), extraction_event(app, second["id"])
    tamper(
        app,
        "update llm_exchanges set user_prompt = 'edited' where id in (:a, :b)",
        a=e1["exchanges"][0]["exchange_id"],
        b=e2["exchanges"][0]["exchange_id"],
    )
    with app.state.session_factory() as db:
        first_event = (
            db.scalars(
                select(AuditEventRow).where(
                    AuditEventRow.report_id == first["id"], AuditEventRow.type == "insight_extracted"
                )
            )
            .one()
            .id
        )

    body = login("auditor").get("/api/audit/verify").json()
    assert body["valid"] is False
    assert body["first_broken_id"] == first_event
    assert body["first_broken_exchange_id"] == e1["exchanges"][0]["exchange_id"]
    assert "Exchange" in body["reason"] and "altered" in body["reason"]


def test_verify_detects_a_removed_exchange(app, login):
    payload = extraction_event(app, upload(login("research_analyst")).json()["id"])
    tamper(app, "delete from llm_exchanges where id = :i", i=payload["exchanges"][0]["exchange_id"])
    body = login("auditor").get("/api/audit/verify").json()
    assert body["valid"] is False and body["first_broken_exchange_id"] == payload["exchanges"][0]["exchange_id"]
    assert "Exchange" in body["reason"] and "missing" in body["reason"]


def test_verify_detects_an_exchange_rewritten_with_a_matching_hash(app, login):
    """Editing the content and recomputing the Exchange's own hash is still caught: the Audit Event pins the original."""
    from app.db import LlmExchangeRow
    from app.exchanges import exchange_digest

    payload = extraction_event(app, upload(login("research_analyst")).json()["id"])
    with app.state.session_factory() as db:
        row = db.get(LlmExchangeRow, payload["exchanges"][0]["exchange_id"])
        row.user_prompt = "rewritten"
        row.hash = exchange_digest(row)
        db.commit()
    body = login("auditor").get("/api/audit/verify").json()
    assert body["valid"] is False and body["first_broken_exchange_id"] == payload["exchanges"][0]["exchange_id"]


def test_events_without_an_exchange_reference_are_pre_capture_not_a_break(app, login):
    legacy = audit.Actor.system("legacy")
    with app.state.session_factory() as db:
        audit.record(db, "memo_generated", legacy, {"status": "complete"})
    body = login("auditor").get("/api/audit/verify").json()
    assert body["valid"] is True and body["checked"] == 1 and body["exchanges_checked"] == 0


def test_governance_reports_capture_health(app, login):
    from app.db import LlmExchangeRow
    from app.exchanges import exchange_digest

    upload(login("research_analyst"))  # one recorded ok exchange, referenced
    upload(
        login("research_analyst"), content=b"A report nobody recorded a reply for.\n"
    )  # one recorded error, referenced
    with app.state.session_factory() as db:
        orphan = LlmExchangeRow(
            created_at="2026-01-01T00:00:00.000000Z",
            task="t",
            prompt_version="p@v1",
            model="m",
            mode="live",
            endpoint_host="h",
            system_text="s",
            user_prompt="u",
            reply_schema_json="{}",
            outcome="ok",
            hash="",
        )
        orphan.hash = exchange_digest(orphan)
        db.add(orphan)
        db.commit()
    r = login("auditor").get("/api/governance")
    assert r.status_code == 200
    assert r.json()["capture_health"] == {
        "total": 3,
        "live": 1,
        "recorded": 2,
        "errors": 1,
        "unreferenced": 1,
        "trajectories": 3,  # each a Trajectory of one
        "assistant_turns": 0,
        "assistant_turns_with_lookups": 0,
        "lookup_share": None,
    }


def test_capture_health_is_all_zero_on_an_empty_database(login):
    assert login("auditor").get("/api/governance").json()["capture_health"] == {
        "total": 0,
        "live": 0,
        "recorded": 0,
        "errors": 0,
        "unreferenced": 0,
        "trajectories": 0,
        "assistant_turns": 0,
        "assistant_turns_with_lookups": 0,
        "lookup_share": None,
    }
