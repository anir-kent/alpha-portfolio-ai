# 2. Architecture Constraints

These constraints bound the solution space. They were set by the source requirements or chosen for the current scope, and each one is either permanent (P) or lifted by the [Target / Production Roadmap](13-roadmap.md) (R).

## 2.1 Technical constraints

The demonstrator never executes trades. It uses synthetic Clients, a committed market snapshot, one FastAPI process and one SQLite file. Run Step progress is in memory; only one Analysis Run can be in flight. LLM pipeline tasks are single schema-bound calls, while the Assistant is a bounded read-only agent (ADR-0010). Performance and scalability are non-goals.

[Detailed architecture constraints catalog](appendices.md#e5-architecture-constraints-catalog).

## 2.2 Organisational constraints

[Detailed architecture constraints catalog](appendices.md#e4-architecture-constraints-catalog).

## 2.3 Conventions

- **Domain language.** Terms from [`GLOSSARY.md`](../../GLOSSARY.md) are used exactly, in code, UI text and this document.
- **Coding standards and checks.** Ruff, mypy, ESLint, Prettier and `tsc` run in pre-commit and in CI; pytest, the frontend build and this document's `check` run in CI. The full list is in `CODING_STANDARDS.md`.
- **Test seams.** Behaviour is tested at the HTTP API on seeded data, with the LLM interface as the only test double. The frontend has no test runner; it is covered by type checks, lint and the manual end-to-end checklist.
- **Documentation.** This document follows arc42 for its sections and C4 for its structural diagrams, written in Mermaid inline. Code-derived tables sit between `BEGIN GENERATED` / `END GENERATED` markers and are rewritten by `uv run python -m scripts.architecture_doc regenerate`. CI's `check` fails when one is stale, a section or link is broken, or a diagram does not render.
- **As-is versus target.** Sections 1 to 12 describe only what the code on the baseline commit does. Anything not yet built lives in the [Target / Production Roadmap](13-roadmap.md).
