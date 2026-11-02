# 02: Audit chain and Auditor search

**What to build:** The single global append-only, hash-chained Audit Event store with lineage parents (ADR-0002), the full list of event types, a verify endpoint reporting the first broken link, and Access denied events from role enforcement. An Auditor view lets the Auditor search events and run chain verification.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Events record actor (user or system with model and prompt version), timestamp, payload, parent IDs, previous hash
- [ ] Rows cannot be updated or deleted through any API
- [ ] Verify endpoint passes on an intact chain and names the first broken link after a deliberate tamper in a test
- [ ] Denied actions from ticket 01 produce searchable Access denied events
- [ ] Search by type, actor, Portfolio, Client, Recommendation, Report and date range
- [ ] Auditor view shows search results and verification outcome; other roles cannot reach it
