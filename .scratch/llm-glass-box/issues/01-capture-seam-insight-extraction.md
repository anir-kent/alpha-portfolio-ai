# 01: Capture seam, end to end for insight extraction

**What to build:** Every LLM call made while ingesting a Report is captured as an LLM Exchange. Upload a Report in recorded mode and an Exchange is stored (success, or an error Exchange when no recording exists), carries a content hash, and is referenced by id and hash from the insight Audit Event on both the success and failure paths. If an Exchange cannot be saved, the call fails closed through the existing LLM error, so the step degrades as it does today. A new `llm:read` permission and a basic single-Exchange read endpoint make the behaviour verifiable through the API. This ticket establishes the wrapper, store, hashing and anchoring pattern that every later ticket reuses. See spec `.scratch/llm-glass-box/spec.md` and ADR-0004.

**Blocked by:** None (can start immediately)

**Status:** done

- [ ] A successful recorded extraction produces one immutable Exchange labelled `recorded`, with task, prompt version, model, system text, user prompt, reply Schema, parsed content and a content hash
- [ ] A call with no recording produces an error Exchange (outcome `error`, error text kept) and the existing "extraction failed" behaviour is unchanged
- [ ] The Audit Event written for the call references `exchange_id` and `exchange_hash` on both success and failure, so it is covered by the existing hash chain
- [ ] A forced failure to write the Exchange makes the call raise the existing LLM error and the step shows as failed, while deterministic features still work
- [ ] The Exchange table is append-only (no update or delete path) and is created by the existing schema bootstrap on an existing database
- [ ] `llm:read` is held by the Auditor, Compliance Officer and Platform Owner roles only; the single-Exchange read endpoint refuses every other role and the refusal is audited as `access_denied`
- [ ] Tests run through the HTTP API with the `login(role)` fixture and the shipped recordings, with no network
