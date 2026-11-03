"""Role-permission matrix. The server is the only enforcement point."""

ROLES = (
    "relationship_manager",
    "advisor",
    "portfolio_manager",
    "research_analyst",
    "compliance_officer",
    "investment_committee",
    "auditor",
    "platform_owner",
)

_CLIENT_WORK = {"queue:read", "portfolio:read", "recommendation:read", "recommendation:decide", "analysis:run", "insight:read"}

PERMISSIONS: dict[str, frozenset[str]] = {
    "relationship_manager": frozenset(_CLIENT_WORK),
    "advisor": frozenset(_CLIENT_WORK | {"client:pii"}),
    "portfolio_manager": frozenset({"portfolio:read", "recommendation:read", "config:read", "insight:read"}),
    "research_analyst": frozenset({"report:upload", "report:read", "insight:approve", "insight:read"}),
    "compliance_officer": frozenset(
        {"portfolio:read", "recommendation:read", "compliance:decide", "approvals:read", "config:read", "client:pii", "insight:read"}
    ),
    "investment_committee": frozenset({"recommendation:read", "committee:decide", "approvals:read"}),
    "auditor": frozenset(
        {"audit:read", "audit:verify", "governance:read", "recommendation:read", "portfolio:read", "config:read", "insight:read"}
    ),
    "platform_owner": frozenset({"config:read", "config:write", "health:read", "governance:read"}),
}

assert set(PERMISSIONS) == set(ROLES)
