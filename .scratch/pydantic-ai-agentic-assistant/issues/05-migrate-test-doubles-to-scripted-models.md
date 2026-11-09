# 05: Migrate every test double to scripted Models

**What to build:** Every LLM test fakes the model at the one seam, the pydantic-ai Model, so the capture path runs under every test. The existing doubles that stub `complete` move to the scripted-model helper and keep asserting the same observable behaviour: the stub LLM in AI Recommendation tests, the blocking and narrative-failing LLMs in Analysis Run tests, the prompt-capturing LLM in Assistant tests, and the Suggested Question and assistant-eval fakes. Spec: "Testing Decisions".

**Blocked by:** 04 (Per-request replay, scripted-model test helper, recordings regenerated)

**Status:** resolved

- [x] No test stubs `complete` any more. Every fake is a scripted (or replay) Model behind capture
- [x] Tests that asserted on prompts now assert on the requests the scripted Model received
- [x] Failure-path tests (transport error, unreadable reply, replay miss, blocking mid-run) express the same scenarios through scripted Models
- [x] Each pipeline step still yields exactly one Exchange anchored as a list of one (asserted in the coverage test)
- [x] Full suite, ruff and mypy are green

## Comments

Resumed the uncommitted migration after Claude Code's usage limit. Completed Standards and Spec reviews and addressed their findings:

- Unexpected provider failures are scripted through the Model seam rather than monkeypatching a pipeline step.
- All four pipeline steps, including Insight extraction, have one-Exchange anchoring coverage; counts are read through the LLM Exchanges API.
- Report upload exercises a scripted Model behind capture.
- Exhausted scripts, callback exceptions and invalid scripted replies fail tests even behind capture; intentionally scripted provider errors remain captured. Regression tests reproduced the swallowed failures before the helper fix.
- Added type annotations at the changed helper and Model boundaries. Both review passes have no outstanding findings.

Validation: full suite 683 passed, 1 skipped; final scripted-helper file 12 passed (including one regression added after full-suite collection). Ruff lint and formatting checks pass; mypy passes for 107 source files; `git diff --check` passes. The suite emits the existing pydantic-graph event-loop deprecation warning.

Changes remain uncommitted at the user's request. Legacy-client deletion remains ticket 06; no Stage 2 implementation was started.
