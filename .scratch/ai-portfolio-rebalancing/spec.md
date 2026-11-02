Status: ready-for-agent

# AI-Powered Portfolio Rebalancing and Prioritization Platform

Source requirements: `specs/AI_Portfolio_Rebalancing_Use_Case_Requirements_and_Scope.md`. Vocabulary follows `GLOSSARY.md`. Decisions respect `docs/adr/0001`, `0002`, `0003`.

## Problem Statement

Wealth advisors and relationship managers review client portfolios manually and periodically. They read research by hand, translate house views into actions inconsistently, spot drift late, and leave weak evidence of what they decided and why. Compliance cannot easily see suitability gaps, and auditors cannot trace a recommendation back to the research behind it.

The deliverable is also a demonstrator for an interview assessment whose central objective is the effective, responsible use of GenAI. It must therefore show GenAI doing real work (reading reports, assessing impact, proposing tilts, explaining) while governance keeps every number and compliance outcome deterministic and every decision human.

## Solution

A local, end-to-end, advisor-assist platform. It ingests Reports, extracts cited Insights, and monitors synthetic Client Portfolios against their Target Allocations. A deterministic engine computes drift, a priority score and Suitability Rule outcomes. A GenAI layer interprets Reports, proposes a bounded Research Tilt, writes rationale, a prioritisation narrative and an advisor memo, and is held to citations by a grounding validator. The engine drafts Recommendations (sets of Trade Lines). Humans decide through a tiered workflow (Advisor always, Compliance on a breach, Investment Committee when high-impact). Every step is recorded in a single hash-chained audit trail that an Auditor can search and verify. Nothing is ever executed.

Three roles get polished React views: Advisor/RM (queue, drill-down, decision), Compliance Officer (suitability flags, exception approval) and Auditor (audit search, lineage, chain verification, governance page). The other roles exist in RBAC and are exercised through the API and a shared approvals panel.

## User Stories

### Advisor / Relationship Manager
1. As an Advisor, I want a ranked queue of Portfolios needing attention, so that I review the most urgent clients first.
2. As an Advisor, I want each queue row to show the priority score, High/Medium/Low label and its four component breakdown (drift, risk, opportunity, urgency), so that I can see why a Portfolio ranks where it does.
3. As an Advisor, I want a short cited "why this client, why now" narrative on each queue row, so that I grasp the situation without opening the Portfolio.
4. As an Advisor, I want to filter and sort the queue by label, risk profile and review-due date, so that I can plan my day.
5. As an Advisor, I want to see which queue items are past their review SLA, so that I can protect SLA compliance.
6. As an Advisor, I want to start an on-demand analysis run, so that the queue reflects the latest data and approved Insights.
7. As an Advisor, I want to open a Portfolio drill-down showing Holdings, actual vs Target Allocation per Asset Class and each Asset-Class Drift against its Tolerance Band, so that I see where it is misaligned.
8. As an Advisor, I want Portfolio Drift shown as one number with its definition, so that I can compare Portfolios.
9. As an Advisor, I want the Client's Risk Profile, objectives, horizon, liquidity needs and Restrictions on the drill-down, so that I judge suitability in context.
10. As an Advisor, I want to see look-through sector exposure including exposure via funds and ETFs, so that hidden concentration is visible.
11. As an Advisor, I want to see the Insights relevant to this Portfolio with citations to Report pages, so that I can verify the research behind the suggestion.
12. As an Advisor, I want to see the LLM-proposed Research Tilt next to what the engine allowed, so that I understand the AI contribution and the bounds applied.
13. As an Advisor, I want a Recommendation made of Trade Lines in percentages and currency amounts, so that the proposal is concrete.
14. As an Advisor, I want each Recommendation to carry a rationale with citations to Report passages and engine figures, so that every action is explained.
15. As an Advisor, I want ungrounded claims visibly flagged and excluded from the memo, so that I am never misled by unsupported statements.
16. As an Advisor, I want an AI-written advisor memo attached to each Recommendation, so that I can reuse it in my client discussion.
17. As an Advisor, I want to see the Suitability Rule results (pass, warning, breach with numbers and rule ID) beside the Recommendation, so that I know if it is compliant.
18. As an Advisor, I want to accept a Recommendation, so that it moves to the next required approval step or to Approved.
19. As an Advisor, I want to reject a Recommendation with a rationale, so that the reason is on record.
20. As an Advisor, I want to modify Trade Lines, so that I can adapt the proposal to what I know about the Client.
21. As an Advisor, I want a modified Recommendation saved as a new linked version and re-checked for suitability immediately, so that my override cannot bypass rules.
22. As an Advisor, I want to be told when my modification creates a breach and that it will need Compliance sign-off, so that I am not surprised.
23. As an Advisor, I want a Recommendation to be marked Superseded when a newer analysis replaces it, so that I never act on stale advice.
24. As an Advisor, I want a clear statement that Approved means "cleared to act on outside this system", so that nobody believes a trade was placed.
25. As a Relationship Manager, I want to see only masked sensitive Client fields, so that I get the context I need without unnecessary PII.
26. As an Advisor, I want to see the history of versions and Decisions on a Portfolio, so that I understand what was previously recommended.
27. As an Advisor, I want to see whether any Decision I take needs Compliance or Investment Committee approval before I submit it, so that I can set expectations.

### Compliance Officer
28. As a Compliance Officer, I want a list of Recommendations pending Compliance with their Suitability breaches, so that I can clear exceptions efficiently.
29. As a Compliance Officer, I want to see each breached rule with its rule ID, limit, actual value and affected Trade Line, so that I judge the exception on facts.
30. As a Compliance Officer, I want to approve an exception with a mandatory rationale, so that the reason is evidenced.
31. As a Compliance Officer, I want to block a non-compliant Recommendation, so that it cannot proceed.
32. As a Compliance Officer, I want to inspect the Recommendation rationale, citations and grounding flags, so that I judge explainability.
33. As a Compliance Officer, I want to see warnings (not just breaches), so that I can spot emerging issues.
34. As a Compliance Officer, I want my approval to be impossible unless the Advisor has already decided, so that the workflow order is enforced.
35. As a Compliance Officer, I want to view Client Restrictions on the Portfolio, so that I can verify restricted-instrument handling.

### Investment Committee Member
36. As an Investment Committee Member, I want high-impact Recommendations to appear in a pending approvals panel, so that I oversee large changes.
37. As an Investment Committee Member, I want to approve or reject with a rationale, so that strategic oversight is evidenced.
38. As an Investment Committee Member, I want the high-impact thresholds to be visible with the Recommendation, so that I know why it reached me.

### Auditor
39. As an Auditor, I want to search Audit Events by type, actor, Portfolio, Client, Recommendation, Report and date range, so that I can answer audit queries.
40. As an Auditor, I want to open any Recommendation and see its full lineage from Report passage to Insight to Research Tilt to Recommendation to Decision, so that traceability is complete.
41. As an Auditor, I want each event to show actor, timestamp, payload, parent events and, for AI events, the model and prompt version, so that evidence is complete.
42. As an Auditor, I want to verify the audit chain and be told the first broken link, so that tampering is detectable.
43. As an Auditor, I want "access denied" events recorded and searchable, so that I can review attempted overreach.
44. As an Auditor, I want to see overrides (modified Recommendations and exception approvals) highlighted, so that I focus on risk.
45. As an Auditor, I want a governance page with a model card, the prompt and version log and the AI quality panel, so that governance evidence is backed by system data.
46. As an Auditor, I want the human-verified marker on hand-transcribed or seed-approved data to be visible, so that I know what was not machine-extracted.

### Research Analyst
47. As a Research Analyst, I want to upload a PDF or text Report through the API, so that new research enters the system.
48. As a Research Analyst, I want Insights extracted from a Report to be pending until I approve them, so that nothing unvetted affects Portfolios.
49. As a Research Analyst, I want to approve or reject each pending Insight through the API, so that the taxonomy stays correct.
50. As a Research Analyst, I want each Insight to carry the sector or Asset Class, direction, confidence and a cited passage, so that it can be validated.

### Portfolio Manager and Platform Owner (lightweight)
51. As a Portfolio Manager, I want RBAC permissions to read Portfolios and drift data through the API, so that dashboards can be added later.
52. As a Platform Owner, I want a configuration endpoint for Tolerance Bands, priority weights, tilt bounds, SLA and approval thresholds, so that the asset is reusable across segments.
53. As a Platform Owner, I want a health endpoint covering database, market-data snapshot age and LLM availability, so that I can monitor the system.
54. As a Platform Owner, I want a refresh script for market data and a seed script for synthetic Clients, so that I can reset the demo.
55. As a Platform Owner, I want secrets read from environment variables with an example file, so that no credentials are hard-coded.

### GenAI behaviour
56. As an Advisor, I want the LLM to extract cited Insights from Reports, so that I do not read them end to end.
57. As an Advisor, I want the LLM to assess how each approved Insight affects a specific Portfolio using look-through exposures, so that impact is Client-specific.
58. As an Advisor, I want the LLM to propose a Research Tilt that the engine then clips to configured bounds, so that AI input is useful but safe.
59. As an Auditor, I want both the proposed and the allowed tilt recorded, so that I can see what the engine changed.
60. As a Compliance Officer, I want every LLM claim validated for a real quote, matching numbers and a valid citation, so that hallucinations are blocked.
61. As an Auditor, I want the AI quality panel to show grounding pass rate, ungrounded-claim counts and adversarial fixture results, so that Responsible GenAI is evidenced.
62. As a Platform Owner, I want the LLM behind a swappable OpenAI-compatible interface, so that an AI gateway can be adopted later.
63. As a developer, I want a recorded-response mode, so that tests and demos run without network access or cost.

### Security and data
64. As any user, I want to log in with a seeded account and an httpOnly session, so that access is controlled.
65. As an Auditor, I want the server to deny and log any action a role is not permitted, so that RBAC is enforced rather than assumed.
66. As a reviewer, I want the README to state that market data is real and Clients are synthetic, so that the data stance matches the specification.
67. As a developer, I want deterministic seeded scenarios (heavy tech, overweight energy, cash drag, restricted-instrument breach, clean Portfolio), so that outcomes are assertable.
68. As a reviewer, I want a clean Portfolio that produces no action, so that the system demonstrably does not over-recommend.

## Implementation Decisions

**Architecture and stack**
- Monorepo: Python 3.13 backend (FastAPI, Pydantic v2, SQLAlchemy over SQLite, managed with uv) and a separate React + TypeScript front end (Vite, Tailwind, shadcn/ui, TanStack Query) using a typed client generated from the backend OpenAPI schema.
- Contract-first: all data crosses typed API contracts; the OpenAPI schema is the contract. External integrations (custody, brokerage, CRM, market data) are stubs or adapters behind contracts.
- Auth: seeded users, server-side session in an httpOnly cookie, no SSO. A role-permission matrix is enforced on the server. Masking of sensitive Client fields is applied in the API layer by role.
- Working UI roles: Advisor/RM, Compliance Officer, Auditor. Investment Committee uses the shared pending-approvals panel. Research Analyst, Portfolio Manager and Platform Owner are RBAC roles reached via API (plus a dashboard or upload page only if time allows).

**Domain modules (deep modules, small interfaces)**
- *Market data adapter*: reads a committed snapshot of prices and instrument metadata (Twelve Data free tier via a refresh script; ~30 instruments across the 11 GICS sectors plus sector and bond ETFs and a cash proxy). Fund sector look-through comes from a hand-built reference file. Source replaceable (ADR-0003).
- *Synthetic data seeder*: deterministic, fixed-seed generation of ~25 Clients across four Risk Profiles and taxable/tax-advantaged accounts, with the planted scenarios.
- *Drift engine*: per-Asset-Class absolute deviation, warn and breach Tolerance Bands per Risk Profile, Portfolio Drift as half the sum of absolute deviations.
- *Suitability engine*: seven Suitability Rules (max equity share by Risk Profile, single-position limit, sector concentration with look-through, minimum cash reserve, Client Restrictions, horizon check, taxable-gain warning). Each returns pass, warning or breach with rule ID and the numbers. Full tax-lot optimisation excluded.
- *Rebalancing engine*: rule-based, band-based. Moves Asset Classes toward target, applies a bounded configurable Research Tilt (default ±2 percentage points per sector or Asset Class), then resolves suitability breaches. Produces Trade Lines in percentages and currency. No optimiser, no return forecasts (ADR-0001).
- *Priority scorer*: deterministic 0–100: drift 40%, risk 30%, opportunity 20% (look-through exposure to sectors with an approved Insight), urgency 10% (days past review-due versus SLA); weights configurable; High ≥ 70, Medium ≥ 40, else Low; breakdown returned with the score.
- *Report ingestion and Insight service*: accepts PDF or text; extracts text with page references; LLM produces structured Insights (sector or Asset Class, direction, confidence, cited passage). Insights start pending; only approved Insights can affect tilts. Sample Reports are the two provided PDFs plus 2–3 synthetic house views. The p3 scorecard of the Q2 research update is hand-transcribed into a seed file recorded as human-verified; the seed approves sample Insights as human-verified.
- *LLM interface*: single OpenAI-compatible interface (gateway-ready, LiteLLM later). Anthropic as the initial provider. Structured outputs with required citations. Prompts are versioned and every call logs model and prompt version. A recorded-response mode backs tests and demos.
- *GenAI tasks*: Insight extraction; Portfolio impact analysis; Research Tilt proposal (engine clips and validates); Recommendation rationale; advisor memo; cited prioritisation narrative per queue row. The LLM never produces numbers or compliance outcomes.
- *Grounding validator*: every claim must carry a citation (Report ID, page and quote, or a named engine figure). Checks (1) the quote appears in the cited passage, (2) every number matches the engine figures, (3) uncited or invalid claims are flagged ungrounded and excluded from the memo while remaining visible to the Advisor.
- *Recommendation lifecycle*: Draft → Pending Advisor (always) → Pending Compliance (only if any rule breach) → Pending Investment Committee (only if high-impact: turnover ≥ 15% of Portfolio or any single Trade Line ≥ 10%, both configurable) → Approved or Rejected; Superseded when replaced. Modifications create a new linked version and re-run suitability. Approved means cleared to act outside the system; nothing executes. Hard invariant: no Recommendation reaches Approved without a human Decision at every required step.
- *Audit log*: single global append-only hash-chained table with lineage parents (ADR-0002). Events: Report ingested, Insight extracted, Insight approved, Analysis run started, Priority scored, Suitability evaluated, Recommendation drafted, Memo generated, Recommendation modified, Decision recorded, Exception approved or blocked, Access denied. Each records actor (user, or system with model and prompt version), timestamp, payload, parent IDs, previous hash. A verify endpoint reports the first break. Rows are never updated or deleted.
- *Analysis runs*: on demand only (API action plus CLI), over all Portfolios; a new run supersedes open Recommendations on the same Portfolio.
- *Governance*: model card, prompt/version log and AI quality panel (grounding pass rate, ungrounded-claim counts, adversarial fixture results) generated from system data.
- *Config*: a single configuration surface for Tolerance Bands, priority weights, tilt bounds, SLA and approval thresholds.

**API surface (contracts, not paths)**: auth and session; queue and Portfolio detail (with masking); analysis run trigger and status; Recommendation read, modify and Decision submission; pending approvals (Compliance, Investment Committee); Report upload and Insight approval; audit search, lineage and verify; governance data; config; health.

**Front end**: invest in visual polish on the three working views: ranked queue with drift and priority visuals, drill-down with actual-vs-target allocation chart and a recommendation panel showing citations and the proposed-versus-allowed tilt, and the audit lineage view.

## Testing Decisions

- Good tests assert external behaviour only: HTTP responses, state transitions, audit contents. They do not assert engine internals or call private functions.
- **Seam 1 (primary)**: the HTTP API contract via a test client against seeded synthetic data and the committed market-data snapshot. Covers queue ranking and priority breakdown, drift and bands, every Suitability Rule with exact numbers on planted scenarios, the Recommendation lifecycle and versioning, tiered approvals, the "no approval without a human" invariant, RBAC and masking per role, access-denied auditing, audit chain integrity and verification, lineage, and the clean Portfolio producing no action.
- **Seam 2 (adapter)**: the LLM interface is the only test double. CI replays recorded responses. Adversarial fixtures (fabricated quote, wrong number, uncited asset call) must be flagged or blocked. Live-model smoke tests run only on demand.
- No separate seam for the market-data adapter; tests use the committed snapshot.
- No UI automation; the front end is type-checked against the generated OpenAPI client and verified by the scripted demo walkthrough.
- Prior art: none (greenfield). Tests written test-first one behaviour at a time.

## Out of Scope

- Automated trade execution, order placement, settlement, custody; the system never changes mandates.
- Live PII, real client data, multi-bank aggregation.
- Customer-facing GenAI or automatic client notification; any free-form chatbot.
- Mean-variance or return-forecast optimisation; full tax-lot optimisation; derivatives pricing; intraday strategies.
- SSO, scheduler for runs, live market feeds.
- Production or regulatory-grade deployment claims.
- Working screens for Research Analyst, Portfolio Manager, Platform Owner and Investment Committee beyond the shared approvals panel (dashboard or upload page only if time allows).
- Portfolio Manager dashboard and the cross-advisor recommendation-consistency metric (deferred).
- UI test automation.

## Further Notes

**Done criteria**: a scripted walkthrough of the planted scenarios from queue to Auditor evidence; a green test suite including the "no approval without a human" invariant and the grounding fixtures; README stating the real-market / synthetic-client data stance.

**Cut line if time runs short, in order**: Portfolio Manager dashboard and consistency metric, then upload page, then the Investment Committee step.

**Build order (tracer bullets)**: (1) seeded data, drift and priority queue end to end through API and a thin UI; (2) Suitability Rules and Recommendation drafting; (3) LLM Insights, tilt proposal, rationale, narrative and grounding; (4) tiered approvals and audit chain with Auditor views; (5) governance page, AI quality panel and React polish.

**Spec-coverage matrix** (original requirement → where it lands)
- AI indispensable (summarise, extract, assess impact, explain, prioritise) → GenAI tasks; prioritisation narrative; Stories 3, 11, 12, 16, 56–58.
- Advisor-assist, no execution → lifecycle "Approved = cleared to act outside system"; Out of Scope; Story 24.
- Suitability first → Suitability engine; Stories 17, 22, 29.
- Explainability → rationale and citations; Stories 14, 15, 32.
- Contract-first → OpenAPI contracts; stubs behind adapters.
- HITL governance → tiered lifecycle and invariant; Stories 18–21, 28–38.
- Responsible GenAI → grounding validator and AI quality panel; Stories 15, 60, 61.
- Auditability → hash-chained audit; Stories 39–46.
- Golden Asset reusability → configuration surface; Story 52.
- Key business questions (attention now, relevant research, misalignment, action, constraints, decision evidence) → queue, Insights, drift, Recommendation, Suitability results, Decision and audit.
- Scope rows (data, reports, assets, AI, optimisation, workflow, governance, security, deployment) → covered above; structured products only where metadata exists (via ETF/reference file); governance documents are generated from system data.
- Personas 1–8 → Stories grouped by persona; PM dashboard deferred.
- Outcomes: advisor productivity (memo, narrative), prioritisation and SLA (score urgency, SLA flag), consistency (deferred metric), suitability governance (rule results, exception trail), reduced drift (drift visibility), auditability (lineage and verify), reusable asset (config, scripts).
