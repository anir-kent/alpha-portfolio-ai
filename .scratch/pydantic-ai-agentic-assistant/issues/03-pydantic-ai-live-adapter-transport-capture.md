# 03: pydantic-ai live adapter with byte-for-byte transport capture

**What to build:** Live LLM calls go through pydantic-ai while the glass box still shows exactly what crossed the wire. The step-facing `complete` call becomes a single-call pydantic-ai Agent over an injected pydantic-ai Model: native structured output over the request's JSON schema, no tools, zero output retries. The reply is still validated by each step's own model. Capture moves to a wrapper around the Model and writes one Exchange per model request (with Trajectory fields from ticket 02). For live calls it stores the request and raw reply bytes seen by a recording `httpx` transport handed to the provider. This is the expand step: the hand-written client stays in place and is still the default until ticket 04. Spec: "LLM layer module", "Capture"; ADR-0010.

**Blocked by:** 02 (Audit Events anchor an ordered LLM Trajectory)

**Status:** resolved

- [x] `pydantic-ai-slim` with the OpenAI and OpenRouter extras is added with `uv add`. No Logfire. Legacy `httpx` client, not `httpx2`
- [x] Before writing code, check the exact names of the structured-dict output type, the OpenRouter routing setting and the wrapper-model request methods with Context7 against the pinned version
- [x] OpenRouter base URL uses the OpenRouter provider with the attribution title and `provider: {require_parameters: true}`. Any other base URL uses the generic OpenAI-compatible provider without them
- [x] SDK `max_retries` is 0. Temperature is omitted when unset, as today
- [x] Capture wrapper writes the Exchange before the caller writes its Audit Event, and keeps today's session binding and savepoint behaviour inside an Analysis Run. A failed save fails the call (fail closed)
- [x] `httpx.MockTransport` tests: stored request messages and raw reply match the bytes on the wire. The attribution title is sent, and `require_parameters` is sent for OpenRouter only. No API key appears in any Exchange. A failing HTTP response produces exactly one request and one error Exchange. An unparseable reply produces an error with the raw reply kept
- [x] Outcome stays transport-level: a reply the step later rejects stays `ok`
