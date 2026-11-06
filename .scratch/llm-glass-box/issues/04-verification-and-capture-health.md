# 04: Verification and capture health

**What to build:** The Auditor's Verify chain action also proves that no referenced Exchange was altered or removed, and the Governance page shows whether the glass box itself is healthy. Tampering with a stored prompt or reply is detected and the first affected Audit Event is named. Events written before capture are treated as pre-capture, not as a break.

**Blocked by:** 03

**Status:** done

- [x] Verification recomputes the hash of every Exchange referenced by an Audit Event and reports the first event whose Exchange is altered or missing, with a clear reason, alongside the existing chain result
- [x] Events with no Exchange reference are skipped as pre-capture and do not fail verification on an existing database
- [x] The Governance response includes capture health: total Exchanges, live versus recorded counts, error count, and Exchanges referenced by no Audit Event
- [x] The Governance page shows a capture-health panel in the existing glass style, with figures in monospace
- [x] The Verify chain badge in the Audit page shows the Exchange result and the tampered-link alert names the Exchange when that is the break
- [x] Tests run through the HTTP API, including a tamper test that edits a stored Exchange and expects verification to fail at the first referencing event
- [x] `npm run typecheck` and `npm run build` pass
