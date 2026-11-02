def test_defaults_are_served(login):
    cfg = login("platform_owner").get("/api/config").json()
    assert set(cfg["tolerance_bands"]) == {"conservative", "moderate", "growth", "aggressive"}
    for band in cfg["tolerance_bands"].values():
        assert 0 < band["warn"] < band["breach"]
    w = cfg["priority_weights"]
    assert w == {"drift": 0.4, "risk": 0.3, "opportunity": 0.2, "urgency": 0.1}
    assert cfg["tilt_bound_pp"] == 2.0
    assert cfg["approval_thresholds"] == {"turnover_pct": 15.0, "trade_line_pct": 10.0}


def test_update_persists_and_is_visible_to_other_roles(login):
    owner = login("platform_owner")
    r = owner.patch("/api/config", json={"sla_days": 5, "tilt_bound_pp": 1.5})
    assert r.status_code == 200
    assert r.json()["sla_days"] == 5
    auditor_view = login("auditor").get("/api/config").json()
    assert auditor_view["sla_days"] == 5
    assert auditor_view["tilt_bound_pp"] == 1.5


def test_invalid_values_are_rejected_without_changing_config(login):
    owner = login("platform_owner")
    before = owner.get("/api/config").json()
    bad = [
        {"priority_weights": {"drift": 0.9, "risk": 0.3, "opportunity": 0.2, "urgency": 0.1}},
        {"tilt_bound_pp": -1},
        {"sla_days": 0},
        {"tolerance_bands": {"growth": {"warn": 5, "breach": 3}}},
    ]
    for body in bad:
        assert owner.patch("/api/config", json=body).status_code == 422, body
    assert owner.get("/api/config").json() == before
