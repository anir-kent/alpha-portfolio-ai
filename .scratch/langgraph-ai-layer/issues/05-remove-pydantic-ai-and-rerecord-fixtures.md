Status: resolved
Blocked by: 02, 04

# Remove pydantic-ai, the direct HTTP client and recorded mode everywhere

## What to build
- Delete the pydantic-ai code and dependency, the old direct-HTTP OpenRouter client and the custom capture/replay transport.
- Migrate the remaining test doubles (`tests/scripted.py` etc.) to LangChain fake chat models.
- **Remove recorded mode from the whole app:**
  - Delete `tests/fixtures/llm/` and `tests.fixtures.regenerate`.
  - Remove the recorded/replay branches in app modules: audit, exchanges, lineage, governance, assistant, routers, health.
  - In the frontend, remove the live/recorded pill, "n/a (replayed)" and the replay-mode messages.
  - Keep Suggested Questions as plain shortcuts.
- `scripts.walkthrough` runs live. `tests/test_walkthrough.py` runs on fake chat models.
- Keep the stored mode on old Exchange rows so that chain verification still passes. If the `mode` column is no longer needed, drop it from the UI only, or write a migration (ADR-0008) only if that keeps verification green.
- Rewrite docs for live-only mode and the graphs: README, `docs/llm_inter_explain.md`, `docs/manual-e2e-guide.md`, `docs/manual-e2e-checklist.md`, `docs/sanity-test-pack.md` and `docs/demo_walkthrough_guide.md`. Amend any ADR that still mentions recorded mode.

## Acceptance criteria
- [ ] No pydantic-ai imports or dependency remain, and uv.lock is updated
- [ ] `grep -riE "pydantic.ai"` across app/, frontend/, tests/, scripts/, docs/, README.md, GLOSSARY.md, pyproject.toml and uv.lock finds nothing, apart from the superseded ADR-0010 and ADR-0011's "replaces pydantic-ai" line. This covers the Assistant (`app/assistant.py`, `app/assistant_agent.py`), `app/pydantic_llm.py` and `tests/scripted.py`
- [ ] `uv pip list` shows no `pydantic-ai*` package. Plain `pydantic` stays for the data models
- [ ] No module outside `get_chat_model` imports a provider package or calls a provider over raw HTTP
- [ ] `grep -riE "recorded|replay|APP_LLM_MODE|RECORDINGS_DIR"` across app/, frontend/src, tests/, scripts/ and docs/ finds only historical mentions (ADR history, old-row handling)
- [ ] The full test suite is green and offline, using fake chat models
- [ ] The walkthrough and a manual smoke run work live against OpenRouter
- [ ] The README, the docs and the demo script describe live-only mode and the graphs (nodes and edges)
