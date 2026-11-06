Status: ready-for-agent

# LLM glass box: every model conversation is captured, anchored in the audit chain and viewable

Vocabulary follows `GLOSSARY.md` (new term: **LLM Exchange**). Decisions respect `docs/adr/0001`, `0002`, `0003` and the new `0004-llm-exchanges-stored-separately-anchored-in-audit-chain`.

## Problem Statement

The platform already says that the LLM only interprets and explains, and it records the model and prompt version on each AI Audit Event. But an Auditor, a Compliance Officer or a platform owner cannot see what the model was actually asked or what it actually answered. The system prompt, the retrieved report passages and figures in the user prompt, the exact request sent to the provider, the raw reply before parsing, the latency and the token usage are not stored anywhere. A failed call leaves no trace at all, and in the default recorded mode nothing distinguishes a replayed answer from a live one. For a system whose central claim is responsible, explainable use of GenAI, "trust the grounding validator" is not enough evidence: reviewers need to read the real conversation and be able to prove it was not altered.

## Solution

Every call through the single LLM interface is captured as an **LLM Exchange**: live calls, replays from recordings (labelled recorded) and failed calls. Exchanges are stored verbatim in their own append-only table, each with a content hash, and the Audit Event that the calling code already writes for that call references the Exchange by id and hash. Chain verification therefore also proves that no referenced Exchange was altered.

Roles with a new `llm:read` permission (Auditor, Compliance Officer, Platform Owner) get an **LLM Exchanges** page under the GATEWAY group: a filterable chronological feed that also streams new Exchanges live while analysis runs, and a drawer showing the Prompt, the reply Schema, the raw and parsed Reply, the Metadata (hashes, tokens, latency, endpoint) and where the Exchange was used, including its grounding verdict. Lineage nodes for AI events link into the same drawer. Advisors never see raw text; they see a short summary of each AI step (mode, latency, grounded counts) inside the existing AI contribution section of a Recommendation. The Governance page shows capture health. Nothing in the glass box can re-run, edit or delete a prompt.

## User Stories

### Auditor
1. As an Auditor, I want every LLM call to be stored as an LLM Exchange with its full prompt and raw reply, so that I can read exactly what the model was asked and what it said.
2. As an Auditor, I want failed calls captured as Exchanges with the error, so that an AI step that quietly fell back is visible rather than silent.
3. As an Auditor, I want each Exchange labelled live or recorded, so that I never mistake a replayed answer for a live one.
4. As an Auditor, I want chain verification to also recompute the hash of every Exchange an Audit Event references, so that altering a stored prompt or reply is detected.
5. As an Auditor, I want verification to name the first Audit Event whose Exchange is missing or altered, so that I know exactly where trust breaks.
6. As an Auditor, I want events from before capture to be treated as pre-capture rather than as a failure, so that verification stays meaningful on an existing database.
7. As an Auditor, I want a chronological feed of all Exchanges, so that I can follow what the model did during a run.
8. As an Auditor, I want to filter the feed by task, prompt version, mode, outcome and date range, so that I can focus on the calls I am reviewing.
9. As an Auditor, I want each feed row to show time, task, prompt version, model, mode, outcome, latency, token counts and the linked Recommendation or Portfolio, so that I can scan without opening anything.
10. As an Auditor, I want to open an Exchange in a drawer with the system text and user prompt, so that I can judge what context the model was given.
11. As an Auditor, I want the drawer to show the reply Schema the model was held to, so that I can judge the reply against it.
12. As an Auditor, I want the drawer to show the raw reply text and a parsed view, so that I can see what was said and how it was read.
13. As an Auditor, I want the drawer to show the Exchange hash, the referenced-by event, token usage, latency, model and endpoint host, so that I can cite the evidence.
14. As an Auditor, I want a "Used by" view listing the Audit Events that reference the Exchange and the grounding verdict on the resulting Claims, so that I can connect what was said to what was accepted.
15. As an Auditor, I want a link from an Exchange to the lineage of its Recommendation, so that I can move from conversation to decision.
16. As an Auditor, I want AI nodes in the lineage view to open the same Exchange drawer, so that I can go from a Recommendation to the conversation behind each AI step.
17. As an Auditor, I want to download a single Exchange as JSON including its hash, so that I can attach the exact record to a review.
18. As an Auditor, I want new Exchanges to appear live in the feed while an analysis runs, so that I can watch the model's activity as it happens.
19. As an Auditor, I want the live feed to resume without gaps after a dropped connection, so that I never miss an Exchange.
20. As an Auditor, I want the feed to fall back to the normal list if the stream is unavailable, so that the page still works.
21. As an Auditor, I want credentials never to appear in any stored Exchange, so that reading evidence cannot leak a key.

### Compliance Officer
22. As a Compliance Officer, I want to open the Exchange behind a Recommendation's rationale or memo, so that I can judge explainability from the real prompt and reply.
23. As a Compliance Officer, I want to see which retrieved passages and figures the model was given, so that I can check that its citations were possible.
24. As a Compliance Officer, I want ungrounded Claims shown next to the reply that produced them, so that I can see where the model went beyond its sources.
25. As a Compliance Officer, I want the same filters and drawer as the Auditor, so that I do not need a second tool.

### Platform Owner
26. As a Platform Owner, I want Governance to show capture health (Exchanges captured, live versus recorded, errors, Exchanges no event references), so that I know the glass box itself is working.
27. As a Platform Owner, I want a failed capture write to make the AI call fail visibly, so that no model output exists without a record.
28. As a Platform Owner, I want to know that switching between live and recorded mode needs no capture configuration, so that the demo and tests behave the same.
29. As a Platform Owner, I want the new permission to be held only by named roles, so that raw prompts are not widely readable.

### Advisor and Relationship Manager
30. As an Advisor, I want each AI step on a Recommendation to show whether it was live or replayed, its latency and its grounded counts, so that I can judge how much to rely on it.
31. As an Advisor, I want no raw prompts or replies exposed to me, so that evidence access stays with reviewers.
32. As a Relationship Manager, I want the same summary without any client detail I am not entitled to see, so that masking is never undermined.
33. As an Advisor, I want a failed AI step to show as failed with its Exchange outcome summarised, so that I know the plain rule-based result is not hiding a problem.

### Researcher and platform integrity
34. As a Research Analyst, I want report ingestion's extraction call captured like any other, so that insight extraction is as explainable as recommendations.
35. As an Auditor, I want all five AI call sites to be captured uniformly, so that no AI step is invisible.
36. As a developer, I want prompts to stay free of client names and emails, enforced by a test, so that granting `llm:read` never leaks client PII.
37. As a developer, I want capture to need no change at the call sites beyond referencing the Exchange in the events they already write, so that new AI steps inherit capture automatically.
38. As an Auditor, I want Exchanges to be immutable once written, so that a later problem is a new record, never an edit.
39. As an Auditor, I want an Exchange's outcome to describe only the transport (reply parsed or error), with a later rejection recorded by the calling step's Audit Event, so that the original conversation is never rewritten.

## Implementation Decisions

- **Concept.** An **LLM Exchange** is one request and reply through the single LLM interface: system text, user prompt, reply Schema, the exact messages sent, the raw reply text, parsed content, model, prompt version, task, mode (live or recorded), endpoint host, latency, token usage, outcome (`ok` or `error`), error text, and a timestamp. Added to `GLOSSARY.md` under Transparency; recorded as ADR-0004.
- **Capture module.** A capturing wrapper sits around the LLM interface where the client is built, so all five call sites are captured without change. It satisfies the same interface as the inner client. It writes one Exchange per call as soon as the reply or error is in, before the caller writes its Audit Event.
- **Fail-closed.** If the Exchange cannot be written, the wrapper raises the existing LLM error. Every call site already degrades gracefully on that error, so drift, suitability and approvals are unaffected.
- **Response and error extensions.** The LLM response gains the Exchange id and hash, plus optional transport detail (messages sent, raw reply text, usage, latency). The LLM error also carries the Exchange id so failure events can reference it. The live adapter fills the transport detail; the recorded adapter fills what it knows and marks tokens and latency as not available (replayed).
- **Exchange store.** A separate append-only table, never updated or deleted, created by the existing schema bootstrap (no migration framework exists). Each row has a SHA-256 content hash over a canonical encoding of its content fields (excluding the row id).
- **Anchoring.** The Audit Event that each call site already writes for the call, on both success and failure paths, carries `exchange_id` and `exchange_hash` in its payload, and so is covered by the existing hash chain. Affected steps: insight extraction, Research Tilt proposal, Recommendation memo and prioritisation narrative.
- **Verification.** The existing chain verification additionally recomputes each referenced Exchange's hash and reports the first event with a missing or mismatched Exchange. Events with no Exchange reference are skipped as pre-capture. No backfill is attempted.
- **Outcome semantics.** The Exchange outcome is transport-level only. A reply that parses but fails the caller's schema validation stays `ok`, and the calling step's Audit Event records the rejection.
- **Grounding verdict.** Not stored on the Exchange. It is joined for display through the referencing Audit Event's check id.
- **Retention.** Everything is kept verbatim with no size cap and no deletion, matching ADR-0002. Production retention and redaction are named as production concerns in ADR-0004.
- **Permissions.** A new `llm:read` permission for the Auditor, Compliance Officer and Platform Owner roles. It is deliberately independent of the client-PII permission. Denied access is audited by the existing access-denied path.
- **Prompt hygiene.** The three prompt builders contain no client names or emails today; this becomes an enforced invariant.
- **API contracts (described, not specified by path).**
  - A paginated, newest-first Exchange list with the filters task, prompt version, mode, outcome and date range, returning summary rows only (no bulk text) plus the linked Recommendation or Portfolio.
  - An Exchange detail returning the full record and the "used by" Audit Events and grounding verdict.
  - A server-sent event stream of new Exchanges, backed by id-based polling at about one-second cadence, honouring the standard last-event-id resume header; it needs no in-process pub/sub, so it works with multiple workers. Authentication reuses the session cookie.
  - All three are gated on `llm:read`.
  - The Governance response gains capture health: totals, live versus recorded, errors, and Exchanges referenced by no event.
  - The lineage node for an AI event gains a short Exchange summary; the Exchange id is included only when the caller holds `llm:read`.
  - The Recommendation's AI contribution gains a per-step summary (mode, latency, grounded counts, outcome) for any role that can read the Recommendation, with no raw text and no id.
- **UI.**
  - A new "LLM Exchanges" item in the GATEWAY nav group, shown only to roles holding `llm:read`.
  - The feed page with filter ribbon, a live-tail toggle with automatic fallback to the list, and the glass-style table.
  - A drawer with tabs for Prompt, Schema, Reply, Metadata and Used by, plus Download JSON.
  - A "View exchange" action on AI nodes in the lineage graph.
  - The AI contribution summary line in the Recommendation panel.
  - A capture-health panel on Governance.
  - All new UI follows the existing frosted-glass design system and keeps figures in monospace.
- **Read-only.** There is no write path from the UI to Exchanges.

## Testing Decisions

- **What makes a good test here.** Assert externally visible behaviour: what the API returns, what the chain verification reports, what an event's payload references. Do not assert how the wrapper is structured internally or which helper computed a hash.
- **One seam.** The HTTP API through `TestClient` with the `login(role)` fixture, as nearly all existing tests do. No lower, wrapper-level seam and no frontend test runner are introduced.
- **Recorded path.** The shipped recordings (insight extraction) exercise success; a call with no recording exercises the error Exchange. Both labelled `recorded`.
- **Live path.** The same API-level tests with the app's LLM adapter pointed at the existing mock-transport pattern, proving the stored body is what was sent, the raw reply is stored before parsing, and usage and latency are captured, with no network.
- **Behaviours to cover.**
  - Capture of all five call paths.
  - An Exchange is referenced by id and hash from the Audit Event on both success and failure.
  - Tampering with a stored Exchange makes verification fail at the first referencing event; a missing Exchange does too; pre-capture events are skipped.
  - Fail-closed: a forced write failure surfaces as the AI step failing while drift, suitability and approvals still work.
  - `llm:read` enforcement: Advisor and Relationship Manager are refused on all three endpoints, the refusals are audited, and the three permitted roles succeed.
  - The Advisor summary exposes no raw text and no Exchange id.
  - Filters and pagination on the list; stream resume from a last-event id.
  - Governance capture health numbers.
  - Credentials never appear in a stored Exchange.
  - PII guard: across seeded clients, no client name or email appears in any captured system or user prompt.
- **Prior art.** The API-level tests with the `login` fixture across the existing suite; the mock-transport live-adapter tests in the research tests; the chain tamper test in the audit tests; the grounding and governance tests for the join and the health panel.
- **UI.** Verified by the type check, the production build and new items in the manual end-to-end checklist (feed, filters, live tail, drawer tabs, lineage link, Advisor summary, capture health).

## Out of Scope

- Re-running a prompt, editing a prompt or replaying a call against a model from the UI.
- Token-level streaming from the provider; capture and the live tail are at Exchange granularity.
- Cost, spend or analytics dashboards across Exchanges.
- Redaction, retention schedules and archival (named as production concerns only).
- Backfilling Exchanges for events written before capture.
- Any change to the grounding validator, the deterministic engine or the approval workflow.
- A frontend automated test runner.

## Further Notes

- In recorded mode the repository ships recordings only for insight extraction, so the tilt, rationale, memo and queue narrative calls produce error Exchanges there. That is a useful demonstration of the fail-visible behaviour, and the manual guide should say so.
- The grilling decisions behind this spec are captured in ADR-0004 and the **LLM Exchange** glossary entry; the working sequence was term, storage and anchoring, capture wiring, failure policy, fidelity, permissions and PII, live transport, UI surfaces, verification, back-compat, tests and scope.
- Suggested ticket slicing for `/to-tickets`: capture seam with fail-closed behaviour for one call site end to end; live transport detail and capture across all call sites with `llm:read` and the PII guard; verification extension and Governance capture health; the Exchange API including the stream; the UI (feed, drawer, lineage link, Advisor summary).
