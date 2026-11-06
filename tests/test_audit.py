import pytest
from sqlalchemy import text

from app.audit import EVENT_TYPES, Actor, record

USER = Actor.user("advisor", "advisor")
AI = Actor.system("insight-extractor", model="claude-sonnet-5-5", prompt_version="v3")


def append(app, type_="report_ingested", actor=USER, payload=None, parents=(), **refs):
    with app.state.session_factory() as db:
        return record(db, type_, actor, payload or {}, parents=parents, **refs)


def events(client, **params):
    r = client.get("/api/audit/events", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_event_records_actor_timestamp_payload_parents_and_previous_hash(app, login):
    first = append(app, payload={"title": "Q2 outlook"}, report_id="R1")
    second = append(app, "insight_extracted", AI, {"sector": "tech"}, parents=[first], report_id="R1")

    items = events(login("auditor"))["items"]
    by_id = {e["id"]: e for e in items}
    a, b = by_id[first], by_id[second]
    assert a["actor"] == {"kind": "user", "name": "advisor", "role": "advisor", "model": None, "prompt_version": None}
    assert a["payload"] == {"title": "Q2 outlook"}
    assert a["parent_ids"] == [] and a["timestamp"]
    assert b["actor"]["kind"] == "system"
    assert (b["actor"]["model"], b["actor"]["prompt_version"]) == ("claude-sonnet-5-5", "v3")
    assert b["parent_ids"] == [first]
    assert b["previous_hash"] == a["hash"]


def test_unknown_event_type_and_missing_parent_are_rejected(app):
    with pytest.raises(ValueError):
        append(app, "not_a_type")
    with pytest.raises(ValueError):
        append(app, parents=[999])


def test_event_types_cover_the_specified_list():
    assert {
        "report_ingested", "insight_extracted", "insight_approved", "analysis_run_started",
        "priority_scored", "suitability_evaluated", "recommendation_drafted", "memo_generated",
        "recommendation_modified", "decision_recorded", "exception_approved", "exception_blocked",
        "access_denied",
    } <= set(EVENT_TYPES)


def test_no_api_updates_or_deletes_events(app, login):
    eid = append(app)
    c = login("auditor")
    for method in ("put", "patch", "delete", "post"):
        assert getattr(c, method)(f"/api/audit/events/{eid}").status_code in (404, 405)
        assert getattr(c, method)("/api/audit/events").status_code in (404, 405)


def test_verify_passes_on_intact_chain(app, login):
    for _ in range(3):
        append(app)
    r = login("auditor").get("/api/audit/verify")
    assert r.status_code == 200
    assert r.json() == {"valid": True, "checked": 3, "first_broken_id": None, "reason": None,
                        "exchanges_checked": 0, "first_broken_exchange_id": None}


def test_verify_on_empty_chain_is_valid(login):
    assert login("auditor").get("/api/audit/verify").json()["valid"] is True


def test_verify_names_first_broken_link_after_payload_tamper(app, login):
    ids = [append(app, payload={"n": i}) for i in range(4)]
    with app.state.session_factory() as db:
        db.execute(text("update audit_events set payload_json = '{\"n\": 99}' where id = :i"), {"i": ids[1]})
        db.execute(text("update audit_events set payload_json = '{\"n\": 98}' where id = :i"), {"i": ids[3]})
        db.commit()
    body = login("auditor").get("/api/audit/verify").json()
    assert body["valid"] is False
    assert body["first_broken_id"] == ids[1]
    assert body["reason"]


def test_verify_detects_deleted_row(app, login):
    ids = [append(app) for _ in range(3)]
    with app.state.session_factory() as db:
        db.execute(text("delete from audit_events where id = :i"), {"i": ids[1]})
        db.commit()
    body = login("auditor").get("/api/audit/verify").json()
    assert body["valid"] is False
    assert body["first_broken_id"] == ids[2]


def test_verify_detects_recomputed_hash_by_relinking(app, login):
    """Rewriting a row's hash without fixing its successor is still caught."""
    ids = [append(app) for _ in range(3)]
    with app.state.session_factory() as db:
        db.execute(text("update audit_events set hash = 'x' where id = :i"), {"i": ids[0]})
        db.commit()
    assert login("auditor").get("/api/audit/verify").json()["first_broken_id"] == ids[0]


def test_denied_action_produces_searchable_access_denied_event(login):
    advisor = login("advisor")
    assert advisor.get("/api/config").status_code == 403
    assert advisor.patch("/api/config", json={"sla_days": 3}).status_code == 403

    denied = events(login("auditor"), type="access_denied")["items"]
    assert len(denied) == 2
    e = denied[0]
    assert e["actor"]["name"] == "advisor" and e["actor"]["role"] == "advisor"
    assert e["payload"]["permission"] in {"config:read", "config:write"}
    assert {d["payload"]["permission"] for d in denied} == {"config:read", "config:write"}
    assert login("auditor").get("/api/audit/verify").json()["valid"] is True


def test_permitted_action_is_not_logged_as_denied(login):
    login("platform_owner").get("/api/config")
    assert events(login("auditor"), type="access_denied")["items"] == []


def test_search_filters(app, login):
    r1 = append(app, "report_ingested", USER, report_id="R1")
    i1 = append(app, "insight_extracted", AI, parents=[r1], report_id="R1")
    d1 = append(app, "recommendation_drafted", AI, parents=[i1], report_id="R1",
                portfolio_id="P1", client_id="C1", recommendation_id="REC1")
    d2 = append(app, "decision_recorded", Actor.user("carol", "advisor"), parents=[d1],
                portfolio_id="P2", client_id="C2", recommendation_id="REC2")
    c = login("auditor")

    def ids(**p):
        return {e["id"] for e in events(c, **p)["items"]}

    assert ids(type="insight_extracted") == {i1}
    assert ids(actor="carol") == {d2}
    assert ids(portfolio_id="P1") == {d1}
    assert ids(client_id="C2") == {d2}
    assert ids(recommendation_id="REC1") == {d1}
    assert ids(report_id="R1") == {r1, i1, d1}
    assert ids(type="decision_recorded", actor="carol", client_id="C2") == {d2}
    assert ids(type="decision_recorded", client_id="C1") == set()


def test_search_by_date_range(app, login):
    eid = append(app)
    c = login("auditor")
    assert len(events(c, date_from="2000-01-01T00:00:00Z", date_to="2999-01-01T00:00:00Z")["items"]) == 1
    assert events(c, date_from="2999-01-01T00:00:00Z")["items"] == []
    assert events(c, date_to="2000-01-01T00:00:00Z")["items"] == []
    assert eid


def test_search_is_newest_first_and_paginated(app, login):
    ids = [append(app) for _ in range(5)]
    body = events(login("auditor"), limit=2, offset=1)
    assert [e["id"] for e in body["items"]] == [ids[3], ids[2]]
    assert body["total"] == 5


@pytest.mark.parametrize("role", [
    "relationship_manager", "advisor", "portfolio_manager", "research_analyst",
    "compliance_officer", "investment_committee", "platform_owner",
])
def test_other_roles_cannot_reach_audit(login, role):
    c = login(role)
    assert c.get("/api/audit/events").status_code == 403
    assert c.get("/api/audit/verify").status_code == 403


def test_audit_requires_authentication(client):
    assert client.get("/api/audit/events").status_code == 401
    assert client.get("/api/audit/verify").status_code == 401
