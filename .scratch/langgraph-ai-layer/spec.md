Status: ready-for-agent

# LangGraph AI layer: every LLM step is an explicit LangGraph graph

Vocabulary follows `GLOSSARY.md` (new terms: **LLM Graph**, **Graph Node**). Decisions respect `docs/adr/0001`, `0002`, `0004` (as amended by 0010), `0005`, `0006`, `0008`, `0009`. A new `0011-llm-steps-are-langgraph-graphs-on-a-captured-transport` supersedes `0010` and answers `0007`'s rejection of LangGraph.

**Docs rule:** every ticket checks the LangGraph / LangChain APIs it touches against current docs via the Context7 MCP (`/websites/langchain_oss_python_langgraph`, `/websites/langchain_oss_python_langchain`) before coding. Follow the documented LangGraph patterns: the "Workflows and agents" guide and the Graph API. Use prebuilt pieces where the docs use them (`ToolNode`, `MessagesState`, `@tool`, `init_chat_model`, `with_structured_output`, `bind_tools`). Don't hand-roll what LangGraph provides, and don't force a higher-level wrapper such as `create_agent` where LangGraph's docs recommend an explicit `StateGraph`. Any deliberate deviation from the documented pattern is written down in ADR-0011 with its reason.

## Problem Statement

The AI layer runs on pydantic-ai (ADR-0010). The Assistant's control flow (agent loop, tools, output validator, one reflection retry, request budget) lives inside the framework's agent loop and is not visible as a structure. The pipeline steps are direct one-shot prompt calls. The model client calls OpenRouter at the HTTP level. The demonstrator exists to show agentic patterns in a regulated setting. The pattern is easier to show, explain to an Auditor and extend when the control flow is an explicit graph of named nodes and edges, built from documented LangGraph components on a swappable model provider.

## Solution

Replace pydantic-ai with LangGraph `StateGraph` (control flow) and a provider-agnostic LangChain chat model from `init_chat_model`. LangGraph's docs say to use LangGraph directly "when you need explicit control over state and control flow", which is this demonstrator's purpose. **Only the AI layer changes.** The engine, audit chain, Screen Context builders, grounding and PII checks, routers, UI and the Analysis Run's transaction behaviour stay as they are.

- **Every LLM step is an LLM Graph** (a compiled `StateGraph`). No step makes a bare prompt → completion call outside a graph.
  - **The four pipeline steps** (Insight extraction, Research Tilt proposal, Recommendation narrative, priority narrative) follow the documented workflow pattern. Each has a typed state, a model node that calls `model.with_structured_output(<existing Pydantic schema>)`, behind the shared `complete` seam. The step fallbacks (Research Tilt → rule-based Recommendation, narratives marked failed) stay in the step code, because they write domain rows and Audit Events, which are outside the AI layer. A step gets a `tools` node only where a read-only lookup is genuinely useful. There is no retry loop: one model request per run.
  - **The Assistant** follows the documented agent pattern, extended with this app's checks. It uses `StateGraph(MessagesState + extra fields)` with these parts:
    - an `agent` node using `model.bind_tools(tools)`;
    - a prebuilt `ToolNode` named `tools` with the read-only, least-privilege lookups from ADR-0010 as `@tool` functions;
    - a conditional edge `agent → tools | validate` (the documented `should_continue` / `tools_condition` routing) and an edge `tools → agent`;
    - a `validate` node running the grounding and PII checks;
    - a conditional edge `validate → agent`, used at most once and naming the ungrounded Claims (the documented evaluator-optimizer loop), or `→ END`. PII failure goes to END with a rejection and no retry;
    - a request budget (default six, `APP_ASSISTANT_REQUEST_LIMIT`): a model-call counter in graph state, checked in the routing before each `agent` run. When it is exceeded, the graph ends the turn with `budget_exhausted`.
- **Provider abstraction:** a single `get_chat_model(task)` factory calls `init_chat_model("<provider>:<model>", ...)`. Provider and model come from config. The default provider is OpenRouter via the dedicated `langchain-openrouter` integration. No module builds HTTP requests to a provider by hand. SDK retries are off (`max_retries=0` or the provider's equivalent).
- **Live mode only. Recorded mode is removed entirely.**
  - Every model call goes to the configured provider. There is no replay, no recordings directory, no `APP_LLM_MODE` and no `APP_LLM_RECORDINGS_DIR`.
  - `tests/fixtures/llm/` and the re-record script (`tests.fixtures.regenerate`) are deleted.
  - The UI drops the live/recorded pill, "n/a (replayed)" and the "Only Suggested Questions work in replay mode" message.
  - Suggested Questions stay, as plain shortcuts.
  - Existing Exchange rows keep their stored mode, so old events still verify. New rows are always live.
- **Tests stay offline** by using LangChain's documented fake chat models (e.g. `GenericFakeChatModel`) as the test double for `get_chat_model`. This is a test double, not a runtime mode.
- **Capture uses a standard LangChain callback.** A callback handler, passed via `config["callbacks"]`, writes one LLM Exchange per model call. It records the messages and parameters sent, the raw reply, token usage, latency, and the Graph Node from callback metadata. This amends ADR-0004: an Exchange stores the request and reply as LangChain sends and receives them, not literal HTTP bytes. The existing custom `httpx` capture/replay transport is deleted.
- **Execution:** sync callers (the Analysis Run) call `graph.invoke`, and async callers use `ainvoke`. A worker-thread wrapper is added only if a documented constraint requires it. The async-tool guard from ADR-0010 is kept if tools stay async.
- **Audit:** an LLM Exchange is still one model call. Each Exchange also records the Graph Node that issued it, taken from the `langgraph_node` callback metadata. The Audit Event's LLM Trajectory (ordered list of exchange id/hash) is unchanged, so no audit-format migration is needed.
- No checkpointer, no interrupts, no LangSmith/tracing. State is per invocation. The Conversation (ADR-0006) and the audit chain are the only records.
- `pydantic-ai-slim` is removed. Pydantic stays for all schemas. The existing data models are reused unchanged for structured output and tool argument schemas.
- **ADRs are updated wherever they get in the way. They are not binding.** ADR-0011 supersedes 0010, amends 0004 (callback capture, no replay, live only) and drops 0007's single-call/no-LangGraph stance. Any other ADR that conflicts is amended in the same ticket that hits the conflict.

## User Stories

1. As a developer, I want every LLM step's control flow to be an explicit LangGraph graph, so that the agentic pattern is readable in one place and matches the LangGraph docs.
2. As an Advisor, I want Assistant behaviour (lookups, permissions, grounding, self-correction, budget, refusals, PII rejection) unchanged, so that nothing regresses.
3. As an Advisor, I want "How I answered" to keep showing lookups, self-correction, requests used and tokens, so that transparency is retained.
4. As an Auditor, I want every model call still stored as its own Exchange with the messages sent and the raw reply, so that the audit record (the "glass box") survives the framework change.
5. As an Auditor, I want each Exchange to name the Graph Node that issued it, so that I can see which step of the graph made each request.
6. As an Auditor, I want chain verification to accept events written before and after this change, so that history is not broken.
7. As a developer, I want one runtime mode (live), so that there are no recordings to keep in sync with prompts, seeds and models.
8. As a developer, I want the pipeline graphs to make one model request with no retry, so that the Analysis Run's write transaction (ADR-0009) is unaffected.
9. As a developer, I want SDK-level retries off, so that every model request is a captured Exchange.
10. As a developer, I want to switch model provider by config, so that OpenRouter is a default, not a hard dependency.
11. As a developer, I want pydantic-ai removed from dependencies, so that there is one framework.

## Implementation Decisions

- New ADR-0011 supersedes ADR-0010 and amends ADR-0004: capture moves from the HTTP transport to a LangChain callback, and replay and recorded mode are removed. GLOSSARY gains **LLM Graph** (the compiled `StateGraph` for one LLM step) and **Graph Node** (a named node in it, e.g. `agent`, `tools`, `validate`).
- One `get_chat_model(task)` factory is the only provider seam. Nothing else imports a provider package.
- Pipeline model nodes use `with_structured_output(Schema)`. The ticket 01 tracer bullet confirms which method (native json_schema vs function calling) the chosen provider uses and that it costs one wire request. Parse and schema errors are not retried and route to the step's existing failure outcome.
- Tools keep ADR-0010's permission-checked, PII-free builders and "not permitted" replies. Unknown and forbidden entities look identical.
- Output validation and the single-retry rule keep today's semantics, implemented as the `validate` node and a conditional edge.
- The request budget is a counter in graph state checked in routing, so it is explicit and visible in the graph.
- Graph topology is code, versioned with the prompt version. It is not recorded per run.

## Testing Decisions

- Test external behaviour: Answers, Trajectories, Exchanges, Audit Events. Do not assert on LangGraph internals.
- Reuse existing Assistant and step tests. Replace scripted pydantic-ai models with LangChain's documented fake chat models (e.g. `GenericFakeChatModel`).
- New tests:
  - Assistant graph paths: lookup → answer; ungrounded → one retry → flagged; PII → rejected; budget → `budget_exhausted`.
  - Pipeline failure edges (Research Tilt fallback, narrative marked failed).
  - A retries-off guard and the async-tool guard (if tools are async).
  - The node name is recorded on Exchanges.
  - The wire shape of structured output for pipeline steps.
  - The provider is switchable by config.
  - Old-event chain verification, including old `recorded` Exchanges.
- The scripted walkthrough (`scripts.walkthrough`) runs live. `tests/test_walkthrough.py` runs on fake chat models.

## Out of Scope

`create_agent` / higher-level agent wrappers, checkpointing, interrupts, multi-agent, write tools, streaming of node events, LangSmith, changes to the Analysis Run structure, any non-AI-layer code.

## Risks to verify early (tracer bullet, ticket 01)

1. `with_structured_output` on the chosen provider returns the existing schema in one model call.
2. With retries off, the callback sees exactly one call per model request.
3. The callback receives `langgraph_node`, the messages, the raw reply and token usage, including on async runs.
4. LangChain's fake chat model can script tool-calling turns and structured output for tests (check `bind_tools` / `with_structured_output` support). If not, use the test approach the LangChain docs recommend.
