# 01: Report ingestion runs off the event loop

**What to build:** Uploading a Report works exactly as today, but the async upload route only reads the upload on the event loop and runs ingestion (which calls the LLM) in the threadpool. That way the LLM layer can later run its own event loop (`run_sync`) without failing inside the server's loop. Prefactor for the pydantic-ai move (spec: "Execution model"; ADR-0010 Consequences).

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] The upload route still reads the file asynchronously and enforces the size limit and `413` as today
- [x] Ingestion, including Insight extraction, runs outside the event loop
- [x] `422` on a Report error and the `201` response body are unchanged
- [x] A test uploads a fixture Report through the async route with a fake LLM that fails if it is called on a thread running an event loop
- [x] Existing research tests pass unchanged
