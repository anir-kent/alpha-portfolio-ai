# 4. Solution Strategy

A handful of decisions shape everything else. Each one is summarised here in a line and recorded in full in its ADR; [9. Architecture Decisions](09-architecture-decisions.md) indexes them all. Read the ADR for the alternatives considered and the consequences.

## 4.1 Shaping decisions

[Detailed shaping decisions and quality goals](appendices.md#e29-shaping-decisions-and-quality-goals). The [ADR index](09-architecture-decisions.md) is the decision authority.

## 4.2 How the decisions fit together

- **Control flow.** An Analysis Run scores every Portfolio deterministically, asks the LLM only for a Research Tilt (which the engine bounds) and for prose (which the Grounding validator checks), then drafts Recommendations for humans to decide through the tiered approval policy. See [6. Runtime View](06-runtime-view.md).
- **Agency, bounded.** Only the Assistant chooses its next step: which read-only lookup to make, and whether to fix a draft the Grounding validator rejected. It never acts, it sees no more than the user's own screens would show, and its whole LLM Trajectory is anchored in one Audit Event. See [6.4 Assistant Question](06-runtime-view.md#64-assistant-question).
- **Evidence.** Business events anchor model evidence in the chain, so an Auditor can trace a Decision back to its Report passage and prompts. Configuration changes and the documented tilt/recording exceptions leave gaps (TD-03/04/05). See [8.2 Audit recording](08-crosscutting-concepts.md#82-audit-recording).
- **Scope trade-off.** The single-process, single-file design keeps the platform runnable with `uv` alone and makes every demo and test repeatable offline. Its costs are named in [11. Risks and Technical Debt](11-risks-and-technical-debt.md), and the [Target / Production Roadmap](13-roadmap.md) lifts them.
- **Technology.** FastAPI and SQLAlchemy on the server, a React SPA with a client generated from the OpenAPI schema, and pydantic-ai over an `httpx` transport, which captures the wire bytes, for any OpenAI-compatible LLM endpoint. The model is swappable by configuration. See [2.1 Technical constraints](02-architecture-constraints.md#21-technical-constraints).
