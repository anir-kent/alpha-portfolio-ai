from tests.conftest import ROLES, SEED_PASSWORD


def test_every_role_has_a_seeded_user_that_can_log_in(client):
    for role in ROLES:
        r = client.post("/api/auth/login", json={"username": role, "password": SEED_PASSWORD})
        assert r.status_code == 200
        assert r.json()["role"] == role


def test_login_sets_httponly_session_cookie_and_me_works(client):
    r = client.post("/api/auth/login", json={"username": "advisor", "password": SEED_PASSWORD})
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["username"] == "advisor"


def test_wrong_password_rejected(client):
    r = client.post("/api/auth/login", json={"username": "advisor", "password": "nope"})
    assert r.status_code == 401
    assert client.get("/api/auth/me").status_code == 401


def test_logout_invalidates_session(login):
    c = login("advisor")
    assert c.post("/api/auth/logout").status_code == 204
    assert c.get("/api/auth/me").status_code == 401


def test_me_reports_permissions_for_role_gated_navigation(login):
    me = login("auditor").get("/api/auth/me").json()
    assert "audit:read" in me["permissions"]
    assert "config:write" not in me["permissions"]
