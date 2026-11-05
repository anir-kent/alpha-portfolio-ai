# 03: Capture across all AI call sites, plus the PII guard

**What to build:** The Research Tilt proposal, the Recommendation rationale and memo, and the prioritisation narrative are captured exactly like insight extraction: one Exchange per call, referenced by id and hash from the Audit Event each step already writes, on both success and failure. No AI step is invisible. A permanent guard test proves that no client name or email ever appears in a captured prompt, which is what lets `llm:read` stand apart from `client:pii`.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Running an analysis on the seeded clients produces Exchanges for the tilt, memo and prioritisation-narrative calls (error Exchanges where recorded mode has no recording)
- [ ] The Audit Event for each of those steps references `exchange_id` and `exchange_hash` on both the success and the failure path
- [ ] A forced Exchange-write failure makes each step show as failed while drift, suitability, queue scoring and approvals still work
- [ ] A new AI step added later inherits capture without call-site changes beyond referencing the Exchange in its Audit Event
- [ ] A guard test runs the AI paths across the seeded clients and fails if any client name or email appears in any captured system or user prompt
- [ ] Tests run through the HTTP API with no network
