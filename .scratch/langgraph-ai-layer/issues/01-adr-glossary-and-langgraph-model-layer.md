Status: resolved
Blocked by: none

# ADR-0011, glossary, provider factory, callback capture, and all four pipeline steps as one LangGraph workflow

## Why all four pipeline steps at once (finding, 2026-11-19)
All four pipeline steps call one seam: `LlmClient.complete(LlmRequest) -> LlmResponse` (`app/llm.py`), at:
- `priority_narrative.py:104`
- `reports.py:201`
- `narrative.py:83`
- `research_tilt.py:176`

Today `ModelLlm.complete` (`app/exchanges.py`) runs `run_single_call` (`app/pydantic_llm.py`) on pydantic-ai. Migrating "one step" would mean two implementations behind one seam. So this ticket reimplements `complete` once, keeping its contract, and every pipeline step moves with it. Step code (`priority_narrative.py`, etc.) should not change.

The Assistant (`app/assistant.py`, `app/assistant_agent.py`) stays on pydantic-ai, `CapturingModel` and `ReplayModel` until tickets 03 and 04. Leave that path working.

## What to build
- **Deps:** already added on this branch (`uv add langgraph langchain langchain-openrouter`, which resolved langgraph 1.2.23 and langchain-openrouter 0.3.0).
- **ADR-0011** (supersedes 0010, amends 0004, drops 0007's no-LangGraph stance), plus **LLM Graph** / **Graph Node** in GLOSSARY.md. Update the GLOSSARY entries that mention recorded/replay.
- **`get_chat_model(settings)`**: `init_chat_model` → `ChatOpenRouter` for an openrouter.ai base URL. It keeps today's behaviour from `build_live_model`:
  - `max_retries=0` (the default is 2);
  - `app_title=OPENROUTER_TITLE`;
  - `openrouter_provider={"require_parameters": True}`;
  - temperature only when set;
  - any other base URL goes through the OpenAI-compatible route.
  
  It is the only module importing a provider package.
- **Capture callback** (`BaseCallbackHandler`, passed in `config["callbacks"]`): one Exchange per model call. Use `on_chat_model_start` for the messages and `on_llm_end` / `on_llm_error` for the reply, usage and error, with latency measured between them. Write the `langgraph_node` from metadata (new column, hand-written migration per ADR-0008; include it in `exchange_digest` only when set, so old rows still hash). It reuses `_Capture._persist`, `bind` (the Analysis Run's session) and `trajectory()` semantics. Fail closed: if the Exchange can't be stored, the call raises `LlmError`. The callback needs `raise_error = True`; verify that it propagates.
- **Pipeline workflow:** a `StateGraph` with typed state and a `generate` node. The node calls `get_chat_model(...).with_structured_output(wire_schema(request.schema), method="json_schema", include_raw=True)` on system + user messages. A `parsing_error`, or a reply that isn't a JSON object, raises `LlmError` carrying the Exchange ref. The step's own Pydantic model still validates afterwards. Behind `complete`, the graph is compiled once.
  - Semantic change to record in ADR-0011: an unparseable reply is now an `ok` Exchange plus a failed step, not an `error` Exchange. Adjust the affected tests.
- **Live only for the pipeline path:** `complete` never replays. Remove `APP_LLM_MODE` / `APP_LLM_RECORDINGS_DIR` / `APP_LLM_RECORD` once the Assistant no longer needs them (ticket 04/05). Until then, they only affect the Assistant.
- **Test double:** the LangChain-documented `FakeToolCallingModel(GenericFakeChatModel)` with `bind_tools` returning self (docs: langchain/test/unit-testing). Inject it where `get_chat_model` is used. Note that base `with_structured_output` on a fake model uses `function_calling` (a tool call of the schema), so give the pipeline node a test seam: either the fake overrides `with_structured_output`, or the script returns JSON content. Pick the simpler one and note it here.
- Migrate the pipeline-step tests off `ScriptedModel`/`ByTask`/replay onto the fake:
  - `test_priority_narrative.py`, `test_research.py`, `test_ai_recommendations.py`, `test_analysis_runs.py`;
  - the pipeline parts of `test_llm_exchange*.py` and `test_llm_live_capture.py`;
  - the pipeline part of `tests/conftest.py`'s `replay_settings` (fixtures in `tests/fixtures/suggested_questions.py`).

## Acceptance criteria
- [x] APIs checked via Context7. Any deviation from the documented pattern is recorded in ADR-0011
- [x] ADR-0011 and glossary written, and ADR-0010 marked superseded
- [x] All four pipeline steps run through the LangGraph workflow live, and their tests run offline on the fake model
- [x] One model call per `complete` with retries off. The Exchange stores the messages, the raw reply, usage, latency and the Graph Node
- [x] The Audit Event Trajectory is a list of one, and old events (including `recorded` Exchanges) still verify
- [x] `get_chat_model` is the only provider import, and a unit test covers provider selection
- [x] The Assistant still works on its current path, and the full suite is green
- [x] Findings on the four spec risks noted here

## Test seam chosen
The fake's `with_structured_output` delegates to `ChatOpenRouter`'s own `json_schema` implementation (same `response_format` binding and parser), and scripts return JSON content (`tests/fake_chat.py`). This is simpler than scripting tool calls, and tests run the production parser chain. Until ticket 05 deletes the recordings, the default test double (`RecordedPipeline`, autouse in `tests/conftest.py`) answers pipeline calls from the committed pipeline recordings. That keeps the seeded run, and so the Screen Context the Assistant's recordings are keyed on, byte-identical.

## Findings on the four spec risks (2026-11-19)
1. **Structured output, one call:** `with_structured_output(schema, method="json_schema", include_raw=True)` sends one request with `response_format.json_schema` (named after the task, set as the schema title) and no tools, on both OpenRouter and the OpenAI-compatible route. An unparseable reply goes to `parsing_error` through a parser fallback, with no second model call. Tested on the wire in `tests/test_llm_live_capture.py`.
2. **Retries off: NOT given by `max_retries=0` on OpenRouter.** `ChatOpenRouter` sets an SDK retry config only when `max_retries > 0`. Otherwise the OpenRouter SDK's per-operation default applies: backoff on 5XX and connection errors for up to an hour (a 503 was sent 7 times in 15 s). `get_chat_model` now builds the `openrouter.OpenRouter` client itself with `RetryConfig("none")`. Recorded as a deviation in ADR-0011. Tests check 503/500/429 and a connection reset each reach the provider once. The OpenAI route honours `max_retries=0`.
3. **Callback data:** `on_chat_model_start` gets `langgraph_node` in metadata, plus the messages and `invocation_params` (with `response_format`). `on_llm_end` gets the `AIMessage` with `usage_metadata` and `response_metadata.model_name`. All of this also arrives on `ainvoke` (prototype). `raise_error = True` propagates a failed save (fail closed, tested). Note: sync `graph.invoke` runs the node on a worker thread. It is safe with the bound Session, because the caller blocks and SQLite uses `check_same_thread=False` (ADR-0011).
4. **Fake model:** `GenericFakeChatModel` + `bind_tools` returning self scripts tool-calling turns (`tests/test_fake_chat.py`). Structured output needs the seam above.

Also found: the `openai` SDK now sends through `httpx2`, not `httpx`. The test network guard (`tests/conftest.py::no_network`) blocks both.

## Notes against the ticket's wording
- The new column is `graph_node` (the glossary term **Graph Node**). Its value is `langgraph_node` from the callback metadata.
- "Only provider import": `get_chat_model` (`app/chat_model.py`) is the only module that imports a LangChain or LangChain-provider package, which `tests/test_chat_model.py` guards. `app/pydantic_llm.py` still imports pydantic-ai's providers for the Assistant, until ticket 05.
- The pipeline tests run on fakes. The default double, `RecordedPipeline`, answers from the committed pipeline recordings only so that the Assistant's Screen-Context-keyed recordings still replay. Ticket 05 deletes both.
- The ADR keeps the filename the spec gave it (`...-on-a-captured-transport`), though capture is now a callback.
