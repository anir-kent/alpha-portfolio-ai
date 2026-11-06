import pytest

from tests.conftest import ROLES


def test_unauthenticated_requests_are_rejected(client):
    assert client.get("/api/config").status_code == 401
    assert client.get("/api/health").status_code == 401


@pytest.mark.parametrize(
    "role,can_read_config,can_write_config",
    [
        ("platform_owner", True, True),
        ("compliance_officer", True, False),
        ("auditor", True, False),
        ("portfolio_manager", True, False),
        ("advisor", False, False),
        ("relationship_manager", False, False),
        ("research_analyst", False, False),
        ("investment_committee", False, False),
    ],
)
def test_config_permissions_by_role(login, role, can_read_config, can_write_config):
    c = login(role)
    assert (c.get("/api/config").status_code == 200) is can_read_config
    if not can_read_config:
        assert c.get("/api/config").status_code == 403
    body = {"sla_days": 7}
    expected = 200 if can_write_config else 403
    assert c.patch("/api/config", json=body).status_code == expected


def test_every_role_is_known_to_the_permission_matrix(login):
    for role in ROLES:
        me = login(role).get("/api/auth/me").json()
        assert isinstance(me["permissions"], list) and me["permissions"]


@pytest.mark.parametrize("role", ROLES)
def test_every_role_may_use_the_assistant(login, role):
    assert "assistant:use" in login(role).get("/api/auth/me").json()["permissions"]
