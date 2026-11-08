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
| **The Assistant is a bounded, read-only agent; every other LLM step stays a single schema-bound call.** All five run on pydantic-ai. The Assistant's lookups reuse the screens' permission-checked builders, its draft is sent back once if Claims are ungrounded, and its requests are capped. No write tools, no multi-agent, no RAG. Supersedes ADR-0007. | Auditability, Explainability, Reproducibility | [ADR-0010](../adr/0010-assistant-is-a-bounded-read-only-agent-on-pydantic-ai.md) |
| **One API process on one SQLite file**, with hand-written idempotent migrations. | Reproducibility (zero-ops local runs); performance and scalability are non-goals | [ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md) |
| **Analysis Run recording commits one Audit Event at a time**: a correction of the record, with the resulting gap kept visible. | Auditability (the record matches the code) | [ADR-0009](../adr/0009-analysis-run-recording-commits-per-audit-event.md) |

## 4.2 How the decisions fit together

- **Control flow.** An Analysis Run scores every Portfolio deterministically, asks the LLM only for a Research Tilt (which the engine bounds) and for prose (which the Grounding validator checks), then drafts Recommendations for humans to decide through the tiered approval policy. See [6. Runtime View](06-runtime-view.md).
- **Agency, bounded.** Only the Assistant chooses its next step: which read-only lookup to make, and whether to fix a draft the Grounding validator rejected. It never acts, it sees no more than the user's own screens would show, and its whole LLM Trajectory is anchored in one Audit Event. See [6.4 Assistant Question](06-runtime-view.md#64-assistant-question).
- **Evidence.** Every business fact and every model request lands in the same chain, so an Auditor can trace a Decision back to the Report passage and the exact prompt behind it. See [8.2 Audit recording](08-crosscutting-concepts.md#82-audit-recording).
- **Scope trade-off.** The single-process, single-file design keeps the platform runnable with `uv` alone and makes every demo and test repeatable offline. Its costs are named in [11. Risks and Technical Debt](11-risks-and-technical-debt.md), and the [Target / Production Roadmap](13-roadmap.md) lifts them.
- **Technology.** FastAPI and SQLAlchemy on the server, a React SPA with a client generated from the OpenAPI schema, and pydantic-ai over an `httpx` transport, which captures the wire bytes, for any OpenAI-compatible LLM endpoint. The model is swappable by configuration. See [2.1 Technical constraints](02-architecture-constraints.md#21-technical-constraints).
