# 08: Advisor AI-step summary

**What to build:** An Advisor or Relationship Manager can judge how far to rely on each AI step without ever seeing raw prompts. In a Recommendation's AI contribution, each AI step shows whether it was live or replayed, its latency, its grounded counts and its outcome. Failed steps show as failed with a short reason. No raw text and no Exchange id is exposed to roles without `llm:read`, and the manual guide explains what recorded mode will show.

**Blocked by:** 03

**Status:** ready-for-agent

- [ ] The Recommendation response carries a per-step summary (mode, latency, grounded and ungrounded counts, outcome) for any role that can read the Recommendation
- [ ] The summary contains no system text, user prompt, reply text or Exchange id for roles without `llm:read`; roles with `llm:read` also get the Exchange id for an "Open exchange" link
- [ ] The AI contribution section shows the summary line beside the existing model and prompt version, with a live or recorded pill and monospace figures
- [ ] A failed step shows as failed with its transport outcome summarised, and the plain rule-based Recommendation is unaffected
- [ ] Relationship Manager masking is unchanged
- [ ] The manual E2E guide notes that recorded mode ships recordings only for insight extraction, so the tilt, rationale, memo and narrative steps show failed Exchanges there, and the checklist gains items for this summary
- [ ] Tests run through the HTTP API with the `login(role)` fixture; `npm run typecheck` and `npm run build` pass
