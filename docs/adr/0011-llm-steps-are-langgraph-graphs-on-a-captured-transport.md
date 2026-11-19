---
status: accepted (pipeline steps); the Assistant follows in later tickets
supersedes: ADR-0010
amends: ADR-0004
---

# LLM steps are LangGraph graphs on a provider-agnostic LangChain chat model, captured by a callback

Every LLM step becomes an **LLM Graph**: a compiled LangGraph `StateGraph` whose control flow is named nodes and edges. This replaces pydantic-ai (ADR-0010) and the hand-written HTTP-level client. It also drops ADR-0007's "no agent framework / no LangGraph" stance, which ADR-0010 had already given up for the Assistant. LangGraph's docs recommend using it directly "when you need explicit control over state and control flow". Showing that control flow to an Auditor is the demonstrator's purpose.

**The four pipeline steps share one graph.** Insight extraction, Research Tilt proposal, the Recommendation narrative and the priority narrative all call one seam, `LlmClient.complete(LlmRequest) -> LlmResponse`. So `complete` is reimplemented once, keeping its contract, and every step moves with it: the step code does not change. The graph is the documented workflow pattern at its smallest. Its typed state holds the request and the reply, and it has one Graph Node, `generate` (START → `generate` → END), compiled once at import. The node makes one model call, `model.with_structured_output(<reply schema>, method="json_schema", include_raw=True)`, on the step's system message (which still carries its reply schema, as ADR-0007 had it) and user message. The schema is sent named after the task. There is no retry edge and no tool node. A `parsing_error`, or a reply that is not a JSON object, raises `LlmError` carrying the Exchange reference. The step's own Pydantic model still validates the reply, and the step fallbacks (Research Tilt → rule-based Recommendation, narratives marked failed) stay in the step code. The chat model is passed as LangGraph runtime context (`context_schema`), so one compiled graph serves the app and every test double.

**One provider seam.** `get_chat_model(settings)` (`app/chat_model.py`) is the only module that imports a provider package. An openrouter.ai base URL selects `init_chat_model("openrouter:<model>")`, i.e. `langchain-openrouter`'s `ChatOpenRouter`. It is given the app's attribution title and `openrouter_provider={"require_parameters": True}`, so OpenRouter routes only to an endpoint that honours the reply schema. Any other base URL selects `init_chat_model("openai:<model>", base_url=...)` (the OpenAI-compatible protocol, `langchain-openai`) with neither. Temperature is sent only when set. SDK retries are off: `max_retries=0`, and see the deviation below.

**Live only for the pipeline.** `complete` never replays: every pipeline call goes to the configured provider. New pipeline Exchanges are always `live`. `APP_LLM_MODE`, `APP_LLM_RECORDINGS_DIR` and `APP_LLM_RECORD` now affect only the Assistant, which stays on pydantic-ai, `CapturingModel` and `ReplayModel` until it becomes an LLM Graph (tickets 03 to 05). Those settings, the recordings and the replay path are removed with it. The chat model is built on first use, so the app still starts without an API key. Without one, the pipeline steps fail through their existing failure outcomes.

## Amendment to ADR-0004

An LLM Exchange is still one model call and its reply, but capture moves from the HTTP transport to a standard LangChain **callback** (`ExchangeCapture`, a `BaseCallbackHandler` passed in `config["callbacks"]`). `on_chat_model_start` notes the messages sent (in OpenAI role/content form), the Graph Node from the callback metadata's `langgraph_node`, and the start time. `on_llm_end` and `on_llm_error` store the Exchange with the reply content, its JSON object when it holds one, the provider's token usage (`usage_metadata`), latency and the Graph Node. So an Exchange stores the request and reply as LangChain sent and received them, not literal HTTP bytes. The API key is in none of those. Error text is still redacted for it, since a provider may echo it back. Capture keeps `_Capture`'s storage, its `bind` to the Analysis Run's session and its `trajectory()` semantics. It fails closed: the callback sets `raise_error = True`, so an Exchange that cannot be stored makes the call raise `LlmError`. A test verifies this.

Each Exchange records its **Graph Node** in a new `graph_node` column (hand-written migration, ADR-0008). The digest covers it only when it is set, so rows written before LLM Graphs keep their stored hashes, recorded ones included. The Audit Event's LLM Trajectory is unchanged: for a pipeline step it is a list of one, and no audit-format migration is needed.

**Semantic change.** Outcome stays transport-level, so a reply that is not JSON is now an `ok` Exchange (it arrived) plus a failed step, where it used to be an `error` Exchange. Its raw reply is kept either way.

## Deviations from the documented pattern, with reasons

- **The OpenRouter SDK client is built in `get_chat_model`.** `ChatOpenRouter(max_retries=0)` does not turn retries off. It passes a retry config to the OpenRouter SDK only when `max_retries > 0`. With none set, the SDK's chat call falls back to its per-operation default: exponential backoff on 5XX responses and connection errors for up to an hour (verified: a 503 was sent 7 times in 15 s). That would hold the Analysis Run's write transaction open (ADR-0009) and send requests capture never sees. So `get_chat_model` gives `ChatOpenRouter` an `openrouter.OpenRouter` client built through the SDK's public constructor, with `RetryConfig("none", ...)`, the same `X-Title` attribution header `ChatOpenRouter` would set, and the old 120 s timeout. A test sends 503, 500, 429 and a connection reset and checks that each reaches the provider exactly once. The OpenAI-compatible route honours `max_retries=0` and is tested the same way.
- **`complete` stays synchronous and LangGraph runs the node on a worker thread.** `graph.invoke` runs the `generate` node, and so the callback, off the caller's thread. Capture still writes through the caller's bound session. That is safe because the caller blocks until `invoke` returns, so the session is used by one thread at a time, and SQLite connections are opened with `check_same_thread=False` (ADR-0008). No worker-thread wrapper is added.
- **Test seam for structured output.** LangChain's documented test double is `GenericFakeChatModel` with `bind_tools` returning itself (`FakeToolCallingModel`). Its base `with_structured_output` uses function calling (a tool call of the schema), not the `json_schema` method the pipeline asks for. Of the two seams the ticket allowed, the simpler one is used: the fake's `with_structured_output` delegates to the OpenRouter integration's own `json_schema` implementation (the same `response_format` binding and output parser), and its script returns JSON content. Tests therefore run the production parser chain.

## Spec risks verified (tracer bullet)

1. `with_structured_output(method="json_schema")` sends one request with `response_format: {type: json_schema, json_schema: {name: <task>, schema}}` and no tools, on both providers. An unparseable reply goes to `parsing_error` through a parser fallback, with no second model call.
2. With retries really off (see the first deviation), the callback sees exactly one call per model request, failures included.
3. The callback receives `langgraph_node`, the messages, the raw reply and `usage_metadata` on sync runs and, in a prototype, on `ainvoke`. The pipeline calls only `invoke`.
4. The fake chat model scripts structured output (through the seam above) and tool-calling turns (`bind_tools` returns itself, so an `AIMessage` with `tool_calls` reaches the caller). Ticket 03 builds the Assistant on this.

## Considered Options

- **Keep pydantic-ai (ADR-0010)**: rejected. The Assistant's control flow (loop, tools, validator, one reflection retry, budget) is hidden inside the framework's agent loop rather than visible as a structure an Auditor can read.
- **`create_agent` or another higher-level wrapper**: rejected. LangGraph's docs recommend an explicit `StateGraph` when control flow is the point, and the pipeline needs no agent.
- **Keep capture at the HTTP transport**: rejected. Each provider SDK has its own HTTP stack (OpenRouter's SDK uses `httpx`, the OpenAI SDK now `httpx2`), so a transport hook is per provider and fragile. The callback is LangChain's documented, provider-agnostic observation point, and the Graph Node is only known there.
- **Two implementations behind `complete` (migrate one step first)**: rejected. All four steps share the seam, so migrating one would mean two capture paths behind one contract.
- **Keep replay for the pipeline**: rejected. One runtime mode means no recordings to keep in sync with prompts, seeds and models. Tests stay offline on the fake chat model, which is a test double, not a runtime mode. Until the Assistant's recordings are removed (ticket 05), the default test double answers pipeline calls from the committed pipeline recordings, so that the seeded demo run, and with it the Screen Context the Assistant's recordings are keyed on, stays identical.
- **Checkpointer, interrupts, LangSmith tracing**: rejected. State is per invocation, and the Conversation (ADR-0006) and the audit chain are the only records.

## Consequences

`langgraph`, `langchain`, `langchain-openrouter` and `langchain-openai` are dependencies. `pydantic-ai-slim` stays until the Assistant moves. A provider is now a config change behind `get_chat_model`, with OpenRouter the default. Exchange `usage` now uses LangChain's keys (`input_tokens`, `output_tokens`, `total_tokens`), which the UI and the Assistant's trajectory summary already read alongside the older `prompt_tokens` and `completion_tokens`. The API exposes each Exchange's `graph_node`. A fresh app in the default `recorded` mode without an API key now runs its Analysis Runs with failed narratives and rule-based Recommendations, where it used to replay them. The demo needs a key, or the Assistant-only replay until ticket 05.

## The Assistant graph (ticket 03)

The Assistant now runs as an LLM Graph, LangGraph's documented tool-calling agent as an explicit `StateGraph(MessagesState)`: an `agent` Graph Node (`model.bind_tools(tools)`), a prebuilt `ToolNode` named `tools`, the prebuilt `tools_condition` edge `agent -> tools | validate`, an edge `tools -> agent`, and a `validate` node that ends the turn. The chat model and the turn's state (`AssistantDeps`) are the graph's runtime context, and tools read the state through `ToolRuntime`. Each model call is an Exchange written by the same `ExchangeCapture` callback as the pipeline's, carrying `graph_node` `agent`. The Trajectory summary is derived from the Exchanges as before. Deviations and interim states, all closed in tickets 04 and 05:

- **Tools are sync.** The graph runs with `invoke` on the router's worker thread, so there is no event loop to block and ADR-0010's async-tool guard has nothing to guard. The `ToolNode` has `handle_tool_errors=False`: a malformed tool call fails the turn, with no tool retry, as before.
- **One lookup.** Only `look_up_portfolio` is ported (ticket 03's tracer bullet). The other six follow in ticket 04.
- **`validate` is a pass-through.** The PII check still runs in `assistant.ask` on the final reply, so no Client-naming answer is stored. Grounding runs on the final reply as before. The one-retry reflection edge and the request budget land in ticket 04, so until then a turn that loops on tools is bounded only by LangGraph's recursion limit.
- **Reply format.** The agent's final message is the JSON reply, as the system prompt's schema asks. Native structured output together with tools is not used.

