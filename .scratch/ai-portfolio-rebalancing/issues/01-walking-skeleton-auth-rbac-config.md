# 01: Walking skeleton: auth, RBAC, config, health

**What to build:** A runnable backend and React shell where a user logs in as a seeded user of any of the eight roles and sees navigation gated by role. The server enforces a role-permission matrix. A configuration surface (Tolerance Bands, priority weights, tilt bounds, SLA, approval thresholds) and a health endpoint exist. The front end uses a typed client generated from the backend OpenAPI schema. Secrets come from environment variables with an example file.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] Seeded users exist for all eight roles; login uses an httpOnly session cookie, no SSO
- [ ] Server rejects actions a role is not permitted to perform (verified via the HTTP API)
- [ ] Config values are readable and updatable only by permitted roles and applied by later engines
- [ ] Health endpoint reports database, market-data snapshot age and LLM availability
- [ ] Front end builds, type-checks against the generated OpenAPI client, and shows role-gated navigation
- [ ] Example env file present; no credentials hard-coded
