# 04: Per-request replay, scripted-model test helper, recordings regenerated

**What to build:** Recorded mode, the default, runs on pydantic-ai and stays deterministic and network-free. A replay Model answers each model request from a recording keyed by a hash of the task, prompt version, reply schema, tool definitions and the full message list so far. A miss raises the recording-missing error, never a guess. Live mode with a record directory writes recordings in this format, one per model request. A project test helper scripts a sequence of replies and tool calls on pydantic-ai's function model and records the requests it received. `build_llm` and the FastAPI dependency now serve the pydantic-ai live or replay Model wrapped in capture. All committed recordings are regenerated. Spec: "Replay"; ADR-0010.

**Blocked by:** 03 (pydantic-ai live adapter with byte-for-byte transport capture)

**Status:** resolved

- [x] Replay Exchanges are labelled `recorded`, as today
- [x] Changing a prompt, the schema, a tool definition or an earlier tool result misses the recording (tested)
- [x] A single command regenerates every committed recording (fixture Reports, pipeline recordings, Suggested Questions, assistant eval). All are regenerated, and the old format is no longer read by the default path
- [x] Real model requests are blocked in the test suite (`ALLOW_MODEL_REQUESTS` off)
- [x] The scripted-model helper can script a multi-request Trajectory, including tool calls, and expose the requests it received for assertions
- [x] The walkthrough and Suggested Questions replay with no network, and each pipeline step still yields one Exchange
