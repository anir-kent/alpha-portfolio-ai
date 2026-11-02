import json
from datetime import datetime, timedelta, timezone


def test_health_reports_database_snapshot_and_llm(login):
    h = login("platform_owner").get("/api/health").json()
    assert h["database"]["status"] == "ok"
    assert h["market_data"]["status"] == "missing"
    assert h["market_data"]["snapshot_age_hours"] is None
    assert h["llm"] == {"status": "ok", "mode": "recorded"}


def test_health_reports_snapshot_age(settings, login):
    ts = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    with open(settings.market_data_snapshot_path, "w") as f:
        json.dump({"as_of": ts}, f)
    h = login("platform_owner").get("/api/health").json()
    assert h["market_data"]["status"] == "ok"
    assert 4.9 < h["market_data"]["snapshot_age_hours"] < 5.2


def test_health_requires_permission(login):
    assert login("advisor").get("/api/health").status_code == 403


def test_liveness_probe_is_unauthenticated_and_leaks_nothing(client):
    r = client.get("/api/health/live")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
