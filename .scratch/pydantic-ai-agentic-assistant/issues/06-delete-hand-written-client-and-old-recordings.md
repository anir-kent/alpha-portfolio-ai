# 06: Delete the hand-written client and the old recording format

**What to build:** The contract step: the platform has one LLM implementation. The hand-written OpenAI-compatible client, the old replay class, the old recording format and any code that only served them are deleted. ADR-0010 supersedes ADR-0007.

**Blocked by:** 05 (Migrate every test double to scripted Models)

**Status:** resolved

- [x] The hand-written OpenAI-compatible client and the old replay class are removed, and no imports of them remain
- [x] Old-format recordings are removed from the repo
- [x] Settings no longer carry options used only by the old client. Any removed setting is noted in the README if it was documented
- [x] Full suite, ruff, mypy and the architecture document check are green

## Comments

Removed the hand-written live client, old replay class, old recording helpers, one-off
`--migrate` fallback and six tests that only exercised the retired clients. Removed all
88 tracked old-format recordings; per-request recordings remain. JSON parsing and schema
normalization remain because the current capture and pydantic-ai adapter use them.

Every LLM setting still serves the current implementation, so no settings were removed.
ADR-0010 already supersedes ADR-0007. The commit hook exposed an outstanding
`RecordedLlm` import in HEAD's Analysis Run tests, hidden by ticket 05's working changes.
The minimum prerequisite migration is included: the Analysis Run tests and scripted
Model helper with its regression tests. Other pre-existing ticket 05 changes remain
uncommitted, including removal of the capture wrapper used by its unmigrated tests.

Validation: 678 passed, 1 skipped (live smoke test); Ruff lint and format checks, mypy
(107 source files), full architecture document check including Mermaid rendering, and
frontend lint, formatting and typechecking passed. Existing event-loop deprecation and
Fast Refresh warnings remain. Standards review: 0 findings. Spec review: 0 findings.
