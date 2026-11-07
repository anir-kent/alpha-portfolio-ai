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
- *LLM interface*: single OpenAI-compatible interface (gateway-ready, LiteLLM later). Anthropic as the initial model, reached through OpenRouter (an OpenAI-compatible gateway, so the model is a config change). Structured outputs with required citations. Prompts are versioned and every call logs model and prompt version. A recorded-response mode backs tests and demos.
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

**Spec-coverage matrix** (original requirement → where it lands → evidence). Every row of the source requirements is accounted for. **Covered** means built and asserted; **Partial** and **Deferred** say what is missing and why; **Out of scope** follows the source document's own Out of Scope column. "Walkthrough act N" is `scripts/walkthrough.py`, which `tests/test_walkthrough.py` runs on every test run.

| Requirement (source section) | Where it lands | Evidence | Status |
| --- | --- | --- | --- |
| AI indispensable: summarise, extract, assess impact, explain, prioritise (§2) | GenAI tasks: Insight extraction, Research Tilt, rationale and memo, prioritisation narrative; Stories 3, 11, 12, 16, 56–58 | `test_research`, `test_ai_recommendations`, `test_priority_narrative`; walkthrough acts 1, 3 | Covered |
| Advisor-assist, not auto-execution (§2, §4) | Lifecycle: "Approved = cleared to act outside this system"; nothing executes; Story 24 | `test_recommendations` (accept executes nothing); UI copy on every Recommendation | Covered |
| Portfolio suitability first: risk profile, horizon, liquidity, restrictions, tax, policy (§2) | Suitability engine, seven rules SR-01…SR-07; Stories 17, 22, 29 | `test_suitability` (exact numbers on planted scenarios); walkthrough acts 2, 3, 5 | Covered (full tax-lot optimisation out of scope) |
| Explainability by design (§2) | Rationale with citations to Report passages and engine figures; Stories 14, 15, 32 | `test_grounding`, `test_ai_recommendations`; walkthrough act 3 | Covered |
| Contract-first integration (§2) | OpenAPI schema is the contract; the frontend's types are generated from the live backend schema; market data, LLM behind adapters | CI runs `npm run gen:api` then `tsc`, so the frontend fails to build against a changed contract; `test_market_data` | Covered (the committed `frontend/openapi.json` is a convenience snapshot, not checked for drift; custody, brokerage, CRM are not integrated: out of scope) |
| Human-in-the-loop governance (§2) | Tiered lifecycle and the "no approval without a human" invariant; Stories 18–21, 28–38 | `test_approvals::test_no_path_reaches_approved_without_a_human_decision_at_every_required_step`; walkthrough acts 4, 5 | Covered |
| Responsible GenAI: grounded, unsupported claims blocked or flagged (§2) | Grounding validator, AI quality panel, adversarial fixtures; Stories 15, 60, 61 | `test_grounding`, `test_governance`; walkthrough acts 3, 7 | Covered |
| Auditability mandatory (§2) | Hash-chained audit with lineage, LLM Exchanges anchored in it (ADR-0002, ADR-0004); Stories 39–46 | `test_audit`, `test_lineage`, `test_llm_exchanges`; walkthrough act 7 | Covered |
| Golden Asset: reusable, configurable constraints and universes (§2, outcome "Reusable AI Asset") | Configuration surface (Story 52), seed and refresh scripts, swappable LLM gateway (OpenRouter by default), Config screen | `test_config`; README Setup and Seed | Covered (a second asset universe is a new snapshot and look-through file; none shipped) |
| Inputs: historical portfolio behaviour (§1) | The snapshot keeps 30 daily closes per Instrument | `data/market_snapshot.json` | Deferred: no engine or prompt uses price history or past Portfolio behaviour yet; drift, scoring and suitability work on the snapshot date |
| Key business questions (§3): attention now, relevant research, misalignment, action, constraints, decision evidence | Queue; approved Insights on the drill-down; drift and look-through; Recommendation; Suitability results; Decision and audit | Walkthrough acts 1–7 in that order | Covered |
| What it must not become (§4): black-box trader, unsupervised robo-advisor, generic chatbot, prompt-only demo | Deterministic engine owns every number (ADR-0001); human Decision at every step; the Assistant is screen-scoped with a scope policy and guardrail eval (`.scratch/sme-assistant/spec.md`) | `test_assistant`, `test_assistant_eval`; governance model card scope policy | Covered |
| Scope: Domain (§5) | Monitoring, drift, insight extraction, recommendation, prioritisation | As above | Covered; execution, orders, settlement, custody out of scope |
| Scope: Customer portfolio data (§5) | Synthetic Clients with profile, risk profile, objective, holdings, targets, restrictions, liquidity needs (ADR-0003); masking by role | `test_seeder`, `test_portfolio` (masking) | Covered; live PII and multi-bank aggregation out of scope |
| Scope: Market and research reports (§5) | PDF/text upload and the Research Analyst review flow; only approved Insights reach Advisors | `test_research`; `.scratch/research-analyst-ui/spec.md` | Covered; social signals and unlicensed reports out of scope |
| Scope: Assets (§5) | Equities, ETFs with look-through, bond ETFs, a cash proxy | `data/market_snapshot.json`, `data/fund_lookthrough.json` | Partial: mutual funds, individual bonds and structured products are not in the snapshot (the free data tier has no metadata for them); a fund is any Instrument with a look-through entry, so adding one is data, not code. Derivatives and intraday out of scope |
| Scope: AI and GenAI (§5) | Summarisation and extraction, impact (tilt), prioritisation narrative, explanation, advisor memo | As for "AI indispensable" | Covered |
| Scope: Optimisation logic (§5) | Rule-based, band-based rebalancing with a bounded Research Tilt (ADR-0001) | `test_recommendations`, `test_ai_recommendations` | Covered; autonomous optimisation out of scope |
| Scope: Advisor workflow (§5) | Ranked queue, drill-down, accept/modify/reject with rationale, audit trail | Walkthrough acts 1–5 | Covered; client communication and notification out of scope |
| Scope: Governance (§5) | Suitability checks, model card, prompt/version log, audit trail, approval workflow, exception management, all generated from system data | `test_governance`; walkthrough act 7 | Covered |
| Scope: Security: RBAC, masking, secrets management (§5) | Server-side role-permission matrix, access-denied auditing, masking in the API layer, `APP_*` secrets from env with `.env.example`, httpOnly session cookie | `test_rbac`, `test_auth`; walkthrough act 6 | Covered |
| Scope: Security: encrypted storage and communication, structured logging (§5) | Not built: local SQLite unencrypted, HTTP on localhost (`APP_COOKIE_SECURE` is ready for TLS); the audit chain is the structured evidence log, application logs are plain | n/a | Partial: a non-production demonstrator (§5 Deployment). Production needs TLS termination, an encrypted database and JSON logs |
| Scope: Deployment (§5) | Local non-production demonstrator on synthetic data | README | Covered; production or regulatory claims out of scope |
| Persona 1–2: Relationship Manager, Investment Advisor (§6) | Queue, drill-down, Recommendation panel; RM masked | Walkthrough acts 1–5 | Covered |
| Persona 3: Portfolio Manager (§6) | RBAC read access to Portfolios, drift and config through the API; read-only Config screen | `test_rbac` | Partial: dashboard, cross-segment comparison and "approve rebalancing logic" deferred (cut line); the rebalancing rules change through config, which only the Platform Owner writes |
| Persona 4: Research Analyst (§6) | Upload, review extracted Insights beside the cited page, approve or reject | `test_research`; manual guide Act 11 | Covered (UI added by `.scratch/research-analyst-ui`) |
| Persona 5–6: Compliance Officer, Investment Committee (§6) | Shared Approvals panel with breaches, thresholds and rationale capture; the committee sees every high-impact Recommendation pending its decision, with the reasons it qualified | `test_approvals`; walkthrough acts 4, 5 | Covered (an aggregated, cross-Portfolio view of asset-class shifts for the committee is deferred) |
| Persona 7: Auditor (§6) | Audit search, lineage, chain verification, governance | `test_audit`, `test_lineage`; walkthrough act 7 | Covered |
| Persona 8: Platform Owner (§6) | Config (`PATCH /api/config`), health (`GET /api/health` and the Health screen), seed and refresh scripts, governance | `test_config`, `test_health`, `test_market_refresh` | Partial: access is the seeded role matrix; no user-management screen (deferred, no SSO in scope) |
| Outcome: advisor productivity (§7) | Narrative per queue row and the advisor memo | Walkthrough acts 1, 3 | Partial: the signal (time to prepare a review note) is not instrumented |
| Outcome: better prioritisation (§7) | Score with drift, risk, opportunity, urgency; SLA flag | `test_drift_priority`, `test_queue` | Partial: "% of High reviewed within SLA" is not reported as a metric |
| Outcome: consistent advisory quality (§7) | Same engine and prompts for every Portfolio | n/a | Deferred: the cross-advisor consistency metric (cut line) |
| Outcome: suitability governance (§7) | Rule results, exception trail with mandatory rationale | `test_approvals`, `test_suitability` | Covered (exception rate derivable from audit search; no dashboard) |
| Outcome: reduced portfolio drift (§7) | Drift visibility and post-trade drift on every Recommendation | `test_recommendations` (returns Portfolio to target) | Covered |
| Outcome: stronger auditability (§7) | Lineage from Report passage to Decision, chain verification | Walkthrough act 7 | Covered |
| Outcome: reusable AI asset (§7) | Config surface, scripts, gateway-agnostic LLM interface | README | Covered |
