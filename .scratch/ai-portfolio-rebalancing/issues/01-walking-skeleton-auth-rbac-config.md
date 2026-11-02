# 01: Walking skeleton: auth, RBAC, config, health

**What to build:** A runnable backend and React shell where a user logs in as a seeded user of any of the eight roles and sees navigation gated by role. The server enforces a role-permission matrix. A configuration surface (Tolerance Bands, priority weights, tilt bounds, SLA, approval thresholds) and a health endpoint exist. The front end uses a typed client generated from the backend OpenAPI schema. Secrets come from environment variables with an example file.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Seeded users exist for all eight roles; login uses an httpOnly session cookie, no SSO
- [x] Server rejects actions a role is not permitted to perform (verified via the HTTP API)
- [x] Config values are readable and updatable only by permitted roles and applied by later engines
- [x] Health endpoint reports database, market-data snapshot age and LLM availability
- [x] Front end builds, type-checks against the generated OpenAPI client, and shows role-gated navigation
- [x] Example env file present; no credentials hard-coded

## Comments

- Implemented in 06d1569 and 90d0e67. 22 backend tests pass; front end builds and type-checks against the generated client.
- Deferred: "access denied" events are not yet written to the audit chain (story 65), pending ticket 02. `require()` in `app/deps.py` is the hook point.
- Role-gated navigation was checked against a live backend over HTTP and via `visibleNav`, not visually in a browser (Chrome extension unavailable).
- `/api/health` needs `health:read` (platform_owner only); `/api/health/live` is an unauthenticated liveness probe.
