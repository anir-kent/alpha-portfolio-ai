# Coding standards

The project follows the widely used standards for its stack: PEP 8 via Ruff on the Python side, and typescript-eslint, the React hooks rules and Prettier on the frontend. Tooling enforces them, so a review never argues about them. The conventions further down are what tooling cannot check.

## Checks

Run these before every commit. All must pass.

| What | Command (from the repo root) |
| --- | --- |
| Python lint (PEP 8, Pyflakes, isort, bugbear, pyupgrade, simplify) | `uv run ruff check` (`--fix` applies the safe fixes) |
| Python format (Black-compatible, 120 columns) | `uv run ruff format` (`--check` in CI) |
| Python types | `uv run mypy` |
| Python tests | `uv run pytest` |
| Frontend lint (ESLint recommended, typescript-eslint recommended, React hooks) | `cd frontend && npm run lint` |
| Frontend format (Prettier, 120 columns) | `cd frontend && npm run format` (`format:check` in CI) |
| Frontend types | `cd frontend && npm run typecheck` |
| Architecture document (sections, links, Mermaid, generated regions) | `uv run python -m scripts.architecture_doc check` (`regenerate` rewrites the generated tables; `--no-mermaid` without Node) |

**Pre-commit** runs the lint, format and type checks on each commit (`.pre-commit-config.yaml`). Set it up once with `uv run pre-commit install`. `uv run pre-commit run --all-files` runs them all by hand. The tests are too slow for a commit hook, so they run in CI.

**CI** (`.github/workflows/ci.yml`) runs every check in the table, the frontend build and the repo-hygiene hooks on each push to `development` or `main` and on every pull request.

Configuration lives in `pyproject.toml` (`[tool.ruff]`, `[tool.mypy]`), `frontend/eslint.config.js`, `frontend/.prettierrc.json` and `.editorconfig`. Change a rule there, not with a scattered `noqa`. When a suppression is genuinely right for one line, give the reason on that line: `# noqa: E731  (reason)` or `// eslint-disable-next-line rule -- reason`.

The whole codebase was reformatted in one commit, listed in `.git-blame-ignore-revs`. To keep `git blame` useful, run once: `git config blame.ignoreRevsFile .git-blame-ignore-revs`.

### Deliberate rule choices

- **E501 (line too long) is off.** The formatter owns line length. Long comments and strings are left alone.
- **B008 knows FastAPI.** `Depends`, `Query`, `Header` and the other parameter markers, and `app.deps.require(permission)`, are allowed as call defaults, because that is how FastAPI declares them.
- **F811 is off in tests.** A pytest fixture imported from another test module is "redefined" when a test takes it as an argument.
- **`react-refresh/only-export-components` is a warning.** Fast refresh is a dev convenience. A module that shares a helper with its components just reloads in full.
- **`_name` marks a binding left unused on purpose**, e.g. a field dropped by a rest destructure.

## Python

- Python 3.13, managed with `uv`. Activate `.venv`, and add packages with `uv add` (`--dev` for tools), never `pip install`.
- Type hints on every function signature. mypy runs with `check_untyped_defs` and the pydantic plugin.
- Use modern syntax: `X | None` rather than `Optional[X]`, built-in generics (`list[str]`), and `datetime.UTC`. Ruff's `UP` rules apply it.
- Re-raise with a cause: `raise DomainError(...) from e`, or `from None` when the original adds nothing (B904).
- Name things in the domain's words (see Domain language below). A loop over Trade Lines uses `line`, not `l` (E741).
- A module docstring says what the module is for and which ADR it follows. A function docstring says what is true after the call, not how it gets there.

## TypeScript and React

- `strict` TypeScript. API types come from the generated `src/api/schema.d.ts` (`npm run gen:api`) and are never written by hand.
- Follow the Rules of Hooks and the React hooks lint, including its React Compiler rules (`set-state-in-effect`, `refs`). Don't write a ref during render: update the "latest handler" ref in an effect.
- Server state belongs to TanStack Query. After a write, invalidate the affected query keys rather than copying data into local state.
- Accessibility is part of done: dialogs trap focus, Escape closes, focus returns to the trigger, live regions are `polite`, and motion honours `prefers-reduced-motion`.

## Domain language and decisions

- Use the terms in `GLOSSARY.md` exactly (Analysis Run, Run Step, Portfolio, Trade Line, Recommendation…) in code, tests, UI text and commit messages.
- Architecture decisions live in `docs/adr/`. Code that departs from an ADR changes the ADR in the same commit.

## Tests

- Test behaviour at the agreed seam, usually the HTTP API: status codes, response bodies, Queue contents, Audit Events. Don't reach into internals.
- Control time and failure only through the dependency overrides the tests already use (the LLM, market data).
- A test name is a sentence that states the behaviour: `test_a_failed_run_keeps_nothing_and_the_queue_still_serves_the_previous_run`.
- The frontend has no test runner. Frontend behaviour is covered by `npm run typecheck`, `npm run lint` and `docs/manual-e2e-checklist.md`.

## Commits

- One logical change per commit. Formatting-only changes go in their own commit, which is listed in `.git-blame-ignore-revs`.
- The subject says what changed. The body says why, and how it was verified (test counts, mypy, typecheck, lint).
