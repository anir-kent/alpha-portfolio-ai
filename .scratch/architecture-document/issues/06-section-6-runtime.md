# 06: §6 Runtime view: four sequence diagrams

**What to build:** A reviewer follows the critical flows end to end: (1) Analysis Run with Run Step progress over SSE, one run at a time, atomic scoring transaction, AI steps; (2) tiered approval of a Recommendation through Advisor, Compliance and Committee Decisions with Audit Events; (3) Report upload → page split → insight extraction → human Insight approval → Grounding; (4) an Assistant Question: permission-filtered Screen Context rebuilt server-side, one LLM call, scope/grounding/PII checks, stored turn and Audit Event, usage limits.

**Blocked by:** 01

**Status:** resolved

- [x] Four Mermaid sequence diagrams render under `check`
- [x] Each diagram shows where Audit Events and LLM Exchanges are written
- [x] Failure paths shown where they matter (replay miss, guardrail refusal, 409 on concurrent run, 429 usage limit)
- [x] Verified against routers and services on the baseline commit; `check` green

## Comments

**2026-11-08, implementation (Claude).**
- `docs/architecture/06-runtime-view.md` has four Mermaid sequence diagrams. Each has an **LLM Exchanges** lane and an **Audit chain** lane, followed by a failure-path table. All four render under `check`.
- **Analysis Run follows ADR-0009, not the ticket's "atomic scoring transaction".** Scoring is one transaction, `record_run` commits one Audit Event at a time, and a final commit marks the run current.
- Verified against the code on this branch: the routers, `analysis*.py`, `run_steps.py`, `recommendations.py`, `approvals.py`, `reports.py`, `grounding.py`, `assistant.py`, `screen_context.py`, `exchanges.py`, `llm.py`, `audit.py` and `deps.py`.
- **Gaps the code shows, now in the document:**
  - A Research Tilt LLM Exchange is never referenced by an Audit Event when the rebalance plan yields no Trade Lines.
  - A failure in the scoring phase rolls back the Research Tilt LLM Exchanges stored under its savepoints.
  - Both belong in §11 (ticket 08).
- **Review:** Standards (glossary terms) and Spec (precision against the code). Both sets of fixes are applied.
- **Verified:** `check` OK. `tests/test_architecture_doc.py` 14 passed. The full pytest run (630 passed, 1 skipped) was before the review edits, which touched only the Markdown.
