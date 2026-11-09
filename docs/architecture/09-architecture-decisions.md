# 9. Architecture Decisions

This section indexes the Architecture Decision Records in `docs/adr/` and does not restate them. Each ADR records the context, the alternatives considered and the consequences, so read the ADR for the reasoning. A decision that changes is corrected by a new ADR, not edited in place. Code that departs from an ADR changes the ADR in the same commit. [4. Solution Strategy](04-solution-strategy.md) shows how the decisions fit together.

| ADR | Decision in one line | Relation |
| --- | --- | --- |
| [ADR-0001](../adr/0001-deterministic-engine-owns-numbers.md) | Deterministic code owns every number, Trade Line and suitability verdict; the LLM only interprets, proposes bounded tilts and explains with citations. | Applied in [8.1](08-crosscutting-concepts.md#81-deterministic-engine-ownership) |
| [ADR-0002](../adr/0002-hash-chained-append-only-audit-log.md) | The audit trail is one append-only, hash-chained table with lineage links. | Applied in [8.2](08-crosscutting-concepts.md#82-audit-recording) |
| [ADR-0003](../adr/0003-market-data-snapshot-synthetic-clients.md) | Real market data comes from a committed snapshot behind an adapter; Clients are synthetic and seeded. | |
| [ADR-0004](../adr/0004-llm-exchanges-stored-separately-anchored-in-audit-chain.md) | Every LLM call is stored as an LLM Exchange in its own append-only table, anchored in the audit chain by hash, failing closed. | Amended by ADR-0010 (LLM Trajectory) |
| [ADR-0005](../adr/0005-run-step-progress-in-process.md) | Run Step progress is held in process memory, and only one Analysis Run is in flight at a time. | Corrected by ADR-0009 |
| [ADR-0006](../adr/0006-assistant-conversations-persisted-and-audited.md) | Assistant Conversations are persisted server-side, append-only and anchored in the audit chain. | |
| [ADR-0007](../adr/0007-llm-steps-are-single-schema-bound-calls.md) | Each LLM step is one schema-bound call through a plain OpenAI-compatible client; no agent framework, agent loop or RAG. | **Superseded** by ADR-0010 |
| [ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md) | One API process on one SQLite file, with hand-written idempotent migrations. | Applied in [8.7](08-crosscutting-concepts.md#87-idempotent-migrations) |
| [ADR-0009](../adr/0009-analysis-run-recording-commits-per-audit-event.md) | An Analysis Run is scored in one transaction, but its recording commits one Audit Event at a time. | Corrects ADR-0005 |
| [ADR-0010](../adr/0010-assistant-is-a-bounded-read-only-agent-on-pydantic-ai.md) | The Assistant is a bounded, read-only tool-using agent on pydantic-ai; every other LLM step stays a single schema-bound call. An Audit Event anchors the step's ordered LLM Trajectory. | Supersedes ADR-0007, amends ADR-0004. Applied in [8.3](08-crosscutting-concepts.md#83-llm-call-shape-and-prompt-versioning) and [6.4](06-runtime-view.md#64-assistant-question) |
