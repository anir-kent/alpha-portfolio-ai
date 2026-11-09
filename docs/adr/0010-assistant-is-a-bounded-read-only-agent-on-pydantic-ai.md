---
status: accepted
supersedes: ADR-0007
amends: ADR-0004
---

# The Assistant is a bounded, read-only tool-using agent on pydantic-ai; every other LLM step stays a single schema-bound call

All five LLM steps now run on pydantic-ai, replacing the hand-written OpenAI-compatible `httpx` client. Insight extraction, Research Tilt proposal, Recommendation narrative and priority narrative remain exactly what ADR-0007 described: one request, one reply held to the step's JSON schema through the provider's native structured output, no tools and no retry. The Assistant is the one step that ADR-0007 named as needing a new decision, "an Assistant that gathers its own context". It becomes an agent. Its first prompt still carries the server-built Screen Context and the Conversation so far as Question and Answer pairs (ADR-0006). It may then call read-only tools that return the Screen Context of other screens through the same permission-checked, PII-free builders, plus the list of approved Insights. Its reply is checked by an output validator. A PII failure rejects the Answer with no retry. Ungrounded Claims trigger exactly one self-correction retry naming the failing Claims, and if Claims are still ungrounded after that they are kept and flagged as before. A Claim may cite engine figures from the Screen Context or from any tool result in the same LLM Trajectory, and the model still never makes up a figure (ADR-0001). An Answer may use at most a configured number of model requests, six by default (`APP_ASSISTANT_REQUEST_LIMIT`). The provider SDK's own retries are off, so every model request is a captured LLM Exchange.

The demonstrator exists partly to show agentic patterns in a regulated setting. This shape shows tool use, a bounded loop, reflection against a deterministic guardrail, least privilege and an auditable trajectory. It does so without letting the model act, choose which figures exist, or escape the glass box.

## Amendment to ADR-0004

An LLM Exchange is still one model request and its reply. An Audit Event now anchors an ordered list of `{exchange_id, exchange_hash}`, called the step's **LLM Trajectory**: a list of one for the single-call steps, possibly several for an Answer. Events written before this change keep their single reference, and verification accepts both forms. Each Exchange records its Trajectory id and position, covered by its content hash. Live capture happens at the HTTP transport handed to pydantic-ai's provider, so the stored request and raw reply are the bytes that crossed the wire, not pydantic-ai's parsed messages. Replays and test models are captured at the model boundary and labelled as such.

## Considered Options

- **Keep the hand-written client (ADR-0007)**: rejected for the Assistant. A fixed prompt cannot follow a question off the current screen. Building a tool loop by hand would re-implement what pydantic-ai already provides, with less scrutiny.
- **Make the pipeline steps agentic too**: rejected. Their inputs are fixed by Insight Review status and engine figures, and they run inside the Analysis Run's write transaction (ADR-0009). Tools would add variable calls and lock time and no capability.
- **Multi-agent (planner and workers, delegation)**: rejected. No question needs it. It multiplies trajectories and authorization surfaces, and one bounded agent is easier to explain to an Auditor.
- **Write tools or actions**: rejected. The Assistant never acts (glossary). Human decisions stay in Insight Review and Decisions.
- **Capture from pydantic-ai hooks or message history**: rejected for live calls. These are parsed objects, not the wire bytes ADR-0004 promises. Capture only tags each model request with its task and prompt version (a context variable the replay and recording Models read to key recordings).
- **Whole-Trajectory replay keyed on the first request**: rejected. A changed tool result would replay a stale continuation. Each model request is replayed by a hash of the task, prompt version, schema, tool definitions and the full message list so far.
- **Tool Output mode (pydantic-ai's default)**: rejected for the single-call steps, which would gain a tool they do not use. Native structured output keeps the wire shape ADR-0007 described.
- **Logfire or OpenTelemetry instrumentation**: rejected. The glass box is the single observability record; a second one could disagree with it.
- **Live streaming of tool steps**: deferred. It needs an async execution path alongside the synchronous app. The Answer arrives whole with its Trajectory summary.
- **`httpx2`**: not adopted. The app and its transport-level capture use `httpx`, which pydantic-ai still accepts.

## Consequences

Every agent tool is `async def`. pydantic-ai runs plain `def` tools in worker threads, which would break the capture client's binding to the caller's database session. A guard enforces this. `run_sync` cannot be called inside a running event loop, so any async route that reaches an LLM step hands the work to the threadpool. Committed recordings change format and are all re-recorded once. A Trajectory replays only when every request in it is identical. An Answer can now use more tokens, and its latency grows with the number of tool calls. The request cap bounds both, and hitting it fails the turn with the reason `budget_exhausted`. The permission split from ADR-0004 holds: Advisors see a summary of the Trajectory's steps, and raw Exchanges still need `llm:read`.
