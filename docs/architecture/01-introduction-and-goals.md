# 1. Introduction and Goals

The Portfolio Rebalancing platform is an advisor-assist and decision-support platform for wealth management. It turns research Reports and Client Portfolio data into explainable, suitability-checked Recommendations that humans review and decide. **It never executes trades:** a Recommendation that reaches Approved is cleared to act on outside this system. The source requirements are `specs/AI_Portfolio_Rebalancing_Use_Case_Requirements_and_Scope.md`, refined in `.scratch/ai-portfolio-rebalancing/spec.md` and the feature specs beside it. Vocabulary follows [`GLOSSARY.md`](../../GLOSSARY.md).

The governing principle runs through every section: **AI proposes, the engine decides, humans approve, everything is audited.**

## 1.1 Requirements overview

The platform answers six business questions. Each is answered by a named capability, and the column on the right says who owns the answer.

[Detailed business capabilities](appendices.md#e3-business-capabilities).

Supporting capabilities: an in-app Assistant that answers Questions about the screen in view, grounded in a server-built Screen Context; a governance page with the model card, the prompt and version log, grounding quality and the adversarial grounding fixture results; an LLM Exchange "glass box" showing what the model saw and said; and read-only Config and Health screens, with configuration changed through the API.

## 1.2 Quality goals

The top quality goals, in priority order. When two conflict, the higher one wins. Each has at least one measurable scenario in [10.2 Quality scenarios](10-quality-requirements.md#102-quality-scenarios).

| Rank | Quality goal | What it means here |
| --- | --- | --- |
| 1 | **Auditability** | Every Insight, Recommendation, Suitability result, Decision, denial and LLM call is traceable end to end, from the Report passage to the human Decision, in a tamper-evident chain that an Auditor can verify ([ADR-0002](../adr/0002-hash-chained-append-only-audit-log.md), [ADR-0004](../adr/0004-llm-exchanges-stored-separately-anchored-in-audit-chain.md)). |
| 2 | **Explainability** | Every number on screen comes from the deterministic engine, and every LLM claim cites a Report passage or an engine figure. Ungrounded claims are flagged and kept out of the memo ([ADR-0001](../adr/0001-deterministic-engine-owns-numbers.md)). |
| 3 | **Human control / safety** | No Recommendation reaches Approved without a human Decision at every required step, the LLM cannot place, size or clear a trade, and nothing is executed. |
| 4 | **Data protection** | Application-derived Client fields use pseudonymous ids in prompts; arbitrary Questions and Reports are not sanitized ([8.9](08-crosscutting-concepts.md#89-pii-stance)). `client:pii` is held by two roles only; authorization is enforced server-side. |
| 5 | **Reproducibility** | The same seed, market data snapshot and recordings give the same Clients, scores, Recommendations and replayed LLM replies, offline ([ADR-0003](../adr/0003-market-data-snapshot-synthetic-clients.md), [ADR-0010](../adr/0010-assistant-is-a-bounded-read-only-agent-on-pydantic-ai.md)). |

**Non-goals for this version: performance and scalability.** The platform is a single-process demonstrator with a handful of concurrent users, one Analysis Run in flight and one writer at a time ([ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md)). No latency, throughput or availability target is set or measured. This is a deliberate scope decision, not an oversight. See [10.3 Non-goals](10-quality-requirements.md#103-non-goals) and the [Target / Production Roadmap](13-roadmap.md).

## 1.3 Stakeholders

### Platform roles

The eight roles are those in `app.rbac.ROLES`. Each user is seeded with one role. The full permission matrix is generated from the code in [8.8 Authentication and authorization](08-crosscutting-concepts.md#88-authentication-and-authorization).

[Detailed stakeholder responsibilities](appendices.md#e2-stakeholder-responsibilities).

Every role may use the Assistant (`assistant:use`). What it sees is still limited by the role's other permissions.

### Review audiences

[Detailed review audiences](appendices.md#e1-review-audiences).
