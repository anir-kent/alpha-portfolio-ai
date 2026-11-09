# 12: Docs, eval and demo script

**What to build:** The documentation, eval and demo all tell the ADR-0010 story. Architecture document sections that still say "one call per step / no agent loop" or cite ADR-0007 (constraints, context and scope, solution strategy, building blocks, runtime view, crosscutting concepts, ADR index) are updated to ADR-0010. The runtime view gains an Assistant Trajectory sequence diagram with its audit and LLM Exchange lanes. The assistant eval gains multi-step cases. The manual E2E checklist gets the interviewer demo script.

**Blocked by:** 06, 08, 09, 10, 11

**Status:** resolved

- [x] No architecture document section contradicts ADR-0010. The ADR index lists 0010 and shows 0007 as superseded. The architecture document check passes, and generated tables are regenerated
- [x] The risk and debt register notes the new risks: Trajectory token cost and latency, and recordings that are brittle to tool-result changes
- [x] The assistant eval is re-recorded and includes at least one cross-screen multi-step case, one self-correction case and one not-permitted case
- [x] The manual E2E checklist has the demo script: a cross-screen Question from the Queue, then "How I answered" (lookups, self-correction, budget), then the same Trajectory on the LLM Exchanges page, then chain verification
- [x] `GLOSSARY.md` and ADR-0010 still match the shipped behaviour (update ADR-0010 if anything changed during the build)

## Comments

- Carried over from 07, which was built with model calls kept offline. The live eval re-record (OpenRouter, `anthropic/claude-sonnet-5.5`) needs explicit approval before it runs, because it sends seeded demo contexts and costs money. Once it runs:
  - commit the new v4+ `data/assistant_eval.json` and remove the strict xfail on `test_the_committed_live_eval_results_are_for_the_current_prompt_version` in `tests/test_governance.py`;
  - replace the authored Suggested Question fixtures in `tests/fixtures/scripted_suggested_questions.py` (including the lookup trajectory) with live recordings via `uv run python -m tests.fixtures.regenerate`.
- Resolved 2026-11-08. Architecture sections 1–6, 8–11 updated to ADR-0010 (ADR index shows 0007 superseded, 0010 added); §6.4 has the Assistant Trajectory sequence diagram; R-10 (Trajectory token cost and latency) and TD-08 (recordings brittle to tool-result changes) added; stale QS test references fixed. `check` (with Mermaid) passes, generated regions current.
- Live eval re-recorded on `assistant_answer@v5` / `anthropic/claude-sonnet-5.5`: 33/33 passed. New cases: `cross_queue_holdings`, `cross_other_drift` (cross-screen), `self_correct_round` (self-correction probe; live, the model declined to round, while 5 other Answers did self-correct once), `not_permitted_holdings`, `not_permitted_approvals`. The old `other_named`/`other_compare` refusals became cross-screen / not-permitted cases, since v5 lets an Advisor look up another Client. The strict xfail was removed.
- Suggested Question re-record was **stopped part-way at the user's request**: 39 Assistant recordings are now live; 18 authored recordings (`scripted-assistant-fixture-v5`) were restored so replay stays green. The `--scripted-assistant` mode and `tests/fixtures/scripted_suggested_questions.py` were removed. To finish: delete the 18 (`git grep -ln scripted-assistant-fixture tests/fixtures/llm | xargs rm`) and rerun `uv run python -m tests.fixtures.regenerate` against OpenRouter (unset any shell `APP_LLM_*` overrides first).
- GLOSSARY.md and ADR-0010 checked against the shipped behaviour; no change needed.
