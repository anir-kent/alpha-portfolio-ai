"""Seam: the HTTP API. Every LLM call made while ingesting a Report is captured as an immutable LLM Exchange that the
insight Audit Event references by id and hash (ADR-0004). Recordings only; no network."""
import json
import re
from pathlib import Path

import pytest
from sqlalchemy import select, text

from app import audit
from app.db import AuditEventRow
from tests.conftest import ROLES

FIXTURES = Path(__file__).parent / "fixtures"
HEX64 = re.compile(r"^[0-9a-f]{64}$")


def upload(c, name="house_view_demo.txt", content=None):
    content = (FIXTURES / name).read_bytes() if content is None else content
    return c.post("/api/reports", files={"file": (name, content)})


def extraction_event(app, report_id):
    with app.state.session_factory() as db:
        row = db.scalars(select(AuditEventRow).where(
            AuditEventRow.report_id == report_id, AuditEventRow.type == "insight_extracted")).one()
        return json.loads(row.payload_json)


def test_recorded_extraction_is_captured_and_anchored_in_the_audit_event(app, login):
    report = upload(login("research_analyst")).json()
    payload = extraction_event(app, report["id"])
    assert HEX64.match(payload["exchange_hash"])

    r = login("auditor").get(f"/api/llm/exchanges/{payload['exchange_id']}")
    assert r.status_code == 200, r.text
    ex = r.json()
    assert ex["hash"] == payload["exchange_hash"]
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

    ex = login("auditor").get(f"/api/llm/exchanges/{payload['exchange_id']}").json()
    assert (ex["outcome"], ex["mode"]) == ("error", "recorded")
    assert "No recorded response" in ex["error"]
    assert ex["hash"] == payload["exchange_hash"]
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
    assert "exchange_id" not in payload and payload["outcome"] == "failed"
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
    exchange_id = extraction_event(app, report["id"])["exchange_id"]
    r = login(role).get(f"/api/llm/exchanges/{exchange_id}")
    if role in ("auditor", "compliance_officer", "platform_owner"):
        assert r.status_code == 200
        return
    assert r.status_code == 403
    with app.state.session_factory() as db:
        denied = db.scalars(select(AuditEventRow).where(AuditEventRow.type == "access_denied")).all()
    assert any(json.loads(d.payload_json)["permission"] == "llm:read" and d.actor_role == role for d in denied)
