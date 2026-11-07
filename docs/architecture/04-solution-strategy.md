# 4. Solution Strategy

A handful of decisions shape everything else. Each one is summarised here in a line and recorded in full in its ADR; [9. Architecture Decisions](09-architecture-decisions.md) indexes them all. Read the ADR for the alternatives considered and the consequences.

## 4.1 Shaping decisions

| Decision | Quality goal it serves | Record |
| --- | --- | --- |
| **AI proposes, the engine decides.** Deterministic code computes every number, Trade Line and suitability verdict; the LLM interprets, proposes a bounded Research Tilt and explains with citations. | Explainability, Human control / safety | [ADR-0001](../adr/0001-deterministic-engine-owns-numbers.md) |
| **One hash-chained, append-only audit trail with lineage**, verified by walking the chain. | Auditability | [ADR-0002](../adr/0002-hash-chained-append-only-audit-log.md) |
| **Real market data from a committed snapshot; synthetic, seeded Clients.** | Reproducibility, Data protection | [ADR-0003](../adr/0003-market-data-snapshot-synthetic-clients.md) |
| **Every LLM call captured as an LLM Exchange** in its own table, anchored in the audit chain by hash, failing closed. | Auditability, Explainability | [ADR-0004](../adr/0004-llm-exchanges-stored-separately-anchored-in-audit-chain.md) |
| **Run Step progress held in process memory**, streamed over SSE, one Analysis Run in flight. | Human control / safety (one current result) | [ADR-0005](../adr/0005-run-step-progress-in-process.md), corrected by [ADR-0009](../adr/0009-analysis-run-recording-commits-per-audit-event.md) |
| **Assistant Conversations persisted server-side, append-only and audited.** | Auditability, Data protection | [ADR-0006](../adr/0006-assistant-conversations-persisted-and-audited.md) |
| **LLM steps are single, schema-bound calls** through a plain OpenAI-compatible client; no agent framework, agent loop or RAG. | Auditability, Reproducibility | [ADR-0007](../adr/0007-llm-steps-are-single-schema-bound-calls.md) |
| **One API process on one SQLite file**, with hand-written idempotent migrations. | Reproducibility (zero-ops local runs); performance and scalability are non-goals | [ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md) |
| **Analysis Run recording commits one Audit Event at a time**: a correction of the record, with the resulting gap kept visible. | Auditability (the record matches the code) | [ADR-0009](../adr/0009-analysis-run-recording-commits-per-audit-event.md) |

## 4.2 How the decisions fit together

- **Control flow.** An Analysis Run scores every Portfolio deterministically, asks the LLM only for a Research Tilt (which the engine bounds) and for prose (which the Grounding validator checks), then drafts Recommendations for humans to decide through the tiered approval policy. See [6. Runtime View](06-runtime-view.md).
- **Evidence.** Every business fact and every model call lands in the same chain, so an Auditor can trace a Decision back to the Report passage and the exact prompt behind it. See [8.2 Audit recording](08-crosscutting-concepts.md#82-audit-recording).
- **Scope trade-off.** The single-process, single-file design keeps the platform runnable with `uv` alone and makes every demo and test repeatable offline. Its costs are named in [11. Risks and Technical Debt](11-risks-and-technical-debt.md), and the [Target / Production Roadmap](13-roadmap.md) lifts them.
- **Technology.** FastAPI and SQLAlchemy on the server, a React SPA with a client generated from the OpenAPI schema, and one `httpx` adapter for any OpenAI-compatible LLM endpoint. The model is swappable by configuration. See [2.1 Technical constraints](02-architecture-constraints.md#21-technical-constraints).
