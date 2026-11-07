# 15: Demo walkthrough, README, polish

**What to build:** A scripted walkthrough of the planted scenarios from queue to Auditor evidence, a README stating the real-market / synthetic-client data stance and how to run, seed, refresh and test, and final visual polish on the Advisor, Compliance and Auditor views.

**Blocked by:** 12, 13, 14

**Status:** resolved

- [x] Walkthrough runs end to end from a fresh seed using recorded responses
- [x] README covers setup, seeding, refresh, running tests and the data stance
- [x] Full test suite is green, including the no-approval-without-a-human invariant and grounding fixtures
- [x] Spec-coverage matrix in the spec has no unaccounted requirement

## Comments

**Resolved 2026-11-07.**
- **Walkthrough:** `uv run python -m scripts.walkthrough` checks 55 claims over 8 acts through the API, on a fresh throwaway seed with recorded responses. `tests/test_walkthrough.py` gates it in the test suite.
- **Recordings:** the first Analysis Run's narratives, Research Tilts and rationale/memos (41 calls), the Assistant's Suggested Questions and the walkthrough's extra calls are recorded against OpenRouter (`anthropic/claude-sonnet-5.5`) with `uv run python -m tests.fixtures.suggested_questions`.
- **Changes needed to record:**
  - OpenRouter calls set `require_parameters`.
  - Temperature is now optional (`APP_LLM_TEMPERATURE`, unset by default), because the model accepts none.
  - `oneOf` is sent as `anyOf`, because Anthropic rejects `oneOf`.
  - The Assistant reply schema declares both citation shapes (`assistant_answer@v3`). The live eval was re-run on v3: 30/30.
- **Exchange capture:** `python -m app.analysis` now captures LLM Exchanges (ADR-0004); before this, the CLI path bypassed capture.
- **Polish:**
  - Read-only Config and Health screens replace the placeholder, and each role opens on its first screen.
  - Suitability rule IDs no longer wrap.
  - The sidebar's first group label is no longer clipped.
  - The lineage view folds each Insight's extraction into its Insight Review card.
- **Docs:** the README is rewritten, the spec-coverage matrix is now an evidenced table, and the manual guide's planted-scenario claims are corrected. C004 has no Recommendation; the Compliance path runs on C002 and the single-approver path on C017.

**Follow-ups, not done:**
- The advisor memo lists one line per Research Tilt, which is long with 13 tilts. Compacting it changes the Recommendation Screen Context, so it needs a re-record.
- `scripts/walkthrough.py` and `tests/fixtures/suggested_questions.py` import each other; move the shared seeding helpers into one neutral module, and consider renaming the recorder.
- The adapter tests in `tests/test_research.py` repeat their MockTransport setup.
- The committed `frontend/openapi.json` is not checked for drift in CI.
