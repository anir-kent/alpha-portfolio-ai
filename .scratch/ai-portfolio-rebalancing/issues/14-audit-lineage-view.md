# 14: Audit lineage view

**What to build:** The Auditor opens any Recommendation and sees its lineage from Report passage through Insight, Research Tilt, Recommendation and Decision, with overrides (modifications and exception approvals) highlighted and human-verified markers visible.

**Blocked by:** 08, 11

**Status:** done

- [x] Lineage is complete for a fully processed planted scenario, including every approval step
- [x] Each node shows actor, timestamp, and model and prompt version for AI events
- [x] Overrides are highlighted
- [x] Human-verified items are marked

## Comments

- Backend: `app/lineage.py` walks audit parent links from a Recommendation's events; `GET /api/recommendations/{id}/lineage` (`audit:read`, so Auditor only). Front end: `LineagePage`, reached from a "Lineage" link on audit search rows that carry a Recommendation.
- Overrides flagged: Advisor modification (its Decision and the new version) and Compliance exception approval. Blocked exceptions are not flagged. Human-verified comes from the event payload flag set by seeding.
- Lineage walks ancestors only, so an earlier version does not show the later modification's events; open the latest version for the full trail.
- Tested at the HTTP API only (7 tests); the page was verified by type-check and build, not visually in a browser.
