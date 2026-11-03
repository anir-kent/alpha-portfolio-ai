# 02: Audit chain and Auditor search

**What to build:** The single global append-only, hash-chained Audit Event store with lineage parents (ADR-0002), the full list of event types, a verify endpoint reporting the first broken link, and Access denied events from role enforcement. An Auditor view lets the Auditor search events and run chain verification.

**Blocked by:** 01

**Status:** done

- [x] Events record actor (user or system with model and prompt version), timestamp, payload, parent IDs, previous hash
- [x] Rows cannot be updated or deleted through any API
- [x] Verify endpoint passes on an intact chain and names the first broken link after a deliberate tamper in a test
- [x] Denied actions from ticket 01 produce searchable Access denied events
- [x] Search by type, actor, Portfolio, Client, Recommendation, Report and date range
- [x] Auditor view shows search results and verification outcome; other roles cannot reach it

## Comments

- Backend: `app/audit.py` (single `record` write path, `verify`, `search`), `app/routers/audit.py`, `audit_events` table; `require()` now writes `access_denied` events. 44 backend tests pass; front end type-checks and builds.
- Rows are protected by having no update/delete path in code or API, plus a unique `previous_hash` so the chain cannot fork. There are no DB-level triggers, so direct SQL can still tamper; that is what `verify` detects.
- Portfolio, Client, Recommendation and Report filters are plain string columns for now; later tickets pass real IDs into `record`.
- Only 403 denials are logged. 401 (unauthenticated) is not.
- Auditor view was verified by type-check and build, not visually in a browser.
