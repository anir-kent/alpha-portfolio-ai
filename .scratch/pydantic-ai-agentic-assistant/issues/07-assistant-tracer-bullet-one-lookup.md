# 07: Assistant tracer bullet: one lookup, end to end

**What to build:** An Advisor on the Queue asks about a Portfolio that isn't on screen. The Assistant looks it up and answers with grounded Claims citing the looked-up figures. Opening "How I answered" on that Answer shows the lookup, its argument, a one-line result summary, requests used against the limit, and tokens. The Assistant becomes a pydantic-ai Agent with the asking user, database session, market data and settings as `deps`. It runs through `run_sync` from the existing synchronous `ask` path and has a single read-only tool, `look_up_portfolio`, built on the existing permission-checked Portfolio Screen Context builder. The turn's Audit Event anchors its multi-Exchange LLM Trajectory. Spec: "Assistant agent", "Assistant turn API and UI"; ADR-0010.

**Blocked by:** 05 (Migrate every test double to scripted Models)

**Status:** resolved

- [x] The first message keeps today's structure: Screen Context, then Question and Answer history (ADR-0006), then the Question. A Suggested Question is still sent without history. No earlier turn's tool calls are carried forward
- [x] `look_up_portfolio` is `async def`, returns the builder's serialised and fenced context, and returns the same "not found or not permitted for your role" result for a forbidden or non-existent id. Tool retry budget is 0
- [x] A guard test fails if any registered Assistant tool is not a coroutine function
- [x] Figures in tool results join the turn's citable figure set, so Claims citing them are Grounded and invented numbers are still flagged
- [x] The Assistant prompt version is bumped. The system text explains the tool, that figures must come from the Screen Context or a lookup, and that "not permitted" must be reported honestly
- [x] `assistant.answered` and `assistant.failed` anchor the ordered Exchange list. A transport error, unreadable reply or replay miss on any request fails the turn with the existing reasons
- [x] The turn API gains a `trajectory` summary (ordered steps, `requests_used`, `request_limit`, tokens) with no raw prompt or reply text. OpenAPI and frontend types are regenerated
- [x] The Assistant drawer shows a collapsed "How I answered" expander per Answer, including the one-step case
- [x] One recorded Suggested Question uses the lookup and replays with no network
- [x] Tests (scripted Model): a cross-screen Trajectory gives a grounded Answer and a two-step summary; a forbidden lookup gives "not permitted" and the Answer says so; a non-existent id gives the same reply

## Comments

- Recordings for the lookup Suggested Question are authored scripted fixtures (`tests/fixtures/scripted_suggested_questions.py`), not live recordings: model calls were kept offline. The live prompt-v4 eval is pending; `test_the_committed_live_eval_results_are_for_the_current_prompt_version` is a strict xfail until `data/assistant_eval.json` is regenerated live.
