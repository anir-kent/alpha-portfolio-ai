# 1. Introduction and Goals

The Portfolio Rebalancing platform is an advisor-assist and decision-support platform for wealth management. It turns research Reports and Client Portfolio data into explainable, suitability-checked Recommendations that humans review and decide. **It never executes trades:** a Recommendation that reaches Approved is cleared to act on outside this system. The source requirements are `specs/AI_Portfolio_Rebalancing_Use_Case_Requirements_and_Scope.md`, refined in `.scratch/ai-portfolio-rebalancing/spec.md` and the feature specs beside it. Vocabulary follows [`GLOSSARY.md`](../../GLOSSARY.md).

The governing principle runs through every section: **AI proposes, the engine decides, humans approve, everything is audited.**

## 1.1 Requirements overview

The platform answers six business questions. Each is answered by a named capability, and the column on the right says who owns the answer.

| Business question | Capability | Owned by |
| --- | --- | --- |
| Which Portfolios need attention now? | An on-demand Analysis Run scores every Portfolio (drift, risk, opportunity, urgency) into a ranked Queue with a cited "why this client, why now" narrative | Deterministic engine (score); LLM (narrative, grounding-checked) |
| Which research is relevant? | Report upload (PDF or text) and Insight extraction with page citations, then an Insight Review by a Research Analyst. Only approved Insights reach an Advisor or feed a score, Research Tilt or narrative | LLM (extraction); Research Analyst (approval) |
| Where is the Portfolio misaligned? | Asset-Class Drift against Tolerance Bands, Portfolio Drift, and look-through sector exposure through funds and ETFs | Deterministic engine |
| What rebalancing action is recommended? | A Recommendation of Trade Lines back to target, optionally adjusted by a Research Tilt the LLM proposes and the engine bounds, with a grounded rationale and advisor memo | Deterministic engine (trades, bounds); LLM (tilt proposal, prose) |
| What suitability constraints apply? | Suitability Rules evaluated before and after trading, each with a pass, warning or breach and its rule id, limit and actual value | Deterministic engine |
| What was decided, and how is it evidenced? | Tiered Decisions (Advisor always, Compliance on a Suitability breach, Investment Committee when turnover or a single Trade Line is at or above its configured threshold), all recorded in one hash-chained audit trail with lineage and LLM Exchange capture | Humans (Decisions); audit chain (evidence) |

Supporting capabilities: an in-app Assistant that answers Questions about the screen in view, grounded in a server-built Screen Context; a governance page with the model card, the prompt and version log, grounding quality and the adversarial grounding fixture results; an LLM Exchange "glass box" showing what the model saw and said; and read-only Config and Health screens, with configuration changed through the API.

## 1.2 Quality goals

The top quality goals, in priority order. When two conflict, the higher one wins. Each has at least one measurable scenario in [10.2 Quality scenarios](10-quality-requirements.md#102-quality-scenarios).

| Rank | Quality goal | What it means here |
| --- | --- | --- |
| 1 | **Auditability** | Every Insight, Recommendation, Suitability result, Decision, denial and LLM call is traceable end to end, from the Report passage to the human Decision, in a tamper-evident chain that an Auditor can verify ([ADR-0002](../adr/0002-hash-chained-append-only-audit-log.md), [ADR-0004](../adr/0004-llm-exchanges-stored-separately-anchored-in-audit-chain.md)). |
| 2 | **Explainability** | Every number on screen comes from the deterministic engine, and every LLM claim cites a Report passage or an engine figure. Ungrounded claims are flagged and kept out of the memo ([ADR-0001](../adr/0001-deterministic-engine-owns-numbers.md)). |
| 3 | **Human control / safety** | No Recommendation reaches Approved without a human Decision at every required step, the LLM cannot place, size or clear a trade, and nothing is executed. |
| 4 | **Data protection** | Client names and emails never leave the platform in a prompt, `client:pii` is held by two roles only, and authorization is enforced on the server alone. |
| 5 | **Reproducibility** | The same seed, market data snapshot and recordings give the same Clients, scores, Recommendations and replayed LLM replies, offline ([ADR-0003](../adr/0003-market-data-snapshot-synthetic-clients.md), [ADR-0007](../adr/0007-llm-steps-are-single-schema-bound-calls.md)). |

**Non-goals for this version: performance and scalability.** The platform is a single-process demonstrator with a handful of concurrent users, one Analysis Run in flight and one writer at a time ([ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md)). No latency, throughput or availability target is set or measured. This is a deliberate scope decision, not an oversight. See [10.3 Non-goals](10-quality-requirements.md#103-non-goals) and the [Target / Production Roadmap](13-roadmap.md).

## 1.3 Stakeholders

### Platform roles

The eight roles are those in `app.rbac.ROLES`. Each user is seeded with one role. The full permission matrix is generated from the code in [8.8 Authentication and authorization](08-crosscutting-concepts.md#88-authentication-and-authorization).

| Role | Expectation of the platform | What they do in it |
| --- | --- | --- |
| Relationship Manager (`relationship_manager`) | Know which Clients need review and why, without seeing more PII than needed | Works the Queue, drill-down and Recommendations like an Advisor, with Client fields masked |
| Advisor (`advisor`) | Turn research into Portfolio-specific, suitable, explained Recommendations | Starts Analysis Runs; accepts, modifies or rejects Recommendations (always the first Decision) |
| Portfolio Manager (`portfolio_manager`) | Monitor drift and alignment across Portfolios | Reads Portfolios, Recommendations, Insights and configuration; decides nothing |
| Research Analyst (`research_analyst`) | Research is interpreted correctly before it reaches an Advisor | Uploads Reports; approves or rejects each extracted Insight beside its cited page |
| Compliance Officer (`compliance_officer`) | Recommendations are suitable and explainable; exceptions are evidenced | Approves an exception with a rationale, or blocks, when a Recommendation is in Suitability breach; reads LLM Exchanges |
| Investment Committee (`investment_committee`) | Oversight of high-impact changes | Decides Recommendations whose turnover or single Trade Line is at or above its configured threshold |
| Auditor (`auditor`) | Evidence, not assertion, from Report to Decision | Searches the audit trail, follows lineage, verifies the chain, runs governance checks, reads LLM Exchanges |
| Platform Owner (`platform_owner`) | Operate and configure the platform safely | Changes configuration, reads health and governance, reads LLM Exchanges |

Every role may use the Assistant (`assistant:use`). What it sees is still limited by the role's other permissions.

### Review audiences

| Audience | Expectation of this document | Where to start |
| --- | --- | --- |
| Architecture Review Board / enterprise architects | The boundary, structure, runtime flows and decisions, with as-is kept apart from target state | §1–§7, [9. Architecture Decisions](09-architecture-decisions.md), [11. Risks and Technical Debt](11-risks-and-technical-debt.md) |
| Model risk reviewers | Exactly what the LLM does and does not decide, the guardrails, the model inventory and measured behaviour | [4. Solution Strategy](04-solution-strategy.md), [Appendices](appendices.md) A–C |
| Compliance reviewers | Segregation of duties as the code applies it, audit evidence and the PII stance | [6. Runtime View](06-runtime-view.md), [8. Crosscutting Concepts](08-crosscutting-concepts.md) |
| InfoSec | Authentication, authorization, secrets, the LLM attack surface and the known gaps | [8.8 Authentication and authorization](08-crosscutting-concepts.md#88-authentication-and-authorization), [Appendix D](appendices.md#appendix-d-security-and-threat-summary), §11 |
| Engineering | Where each responsibility lives and the conventions to follow | [5. Building Block View](05-building-block-view.md), [8. Crosscutting Concepts](08-crosscutting-concepts.md) |
| Business sponsors and GTM | The value and the story in two pages | [Executive Summary](00-executive-summary.md) |
| Document owner (Aniruddh Kendurkar, Principal AI/Data Architect) | A living baseline that cannot drift silently from the code | [Document control](index.md#document-control) |
