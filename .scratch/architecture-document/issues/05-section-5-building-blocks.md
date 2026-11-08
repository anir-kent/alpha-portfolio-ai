# 05: §5 Building blocks: C4 L2 Containers and L3 Components

**What to build:** An engineer or reviewer sees the platform's structure at two zoom levels. C4 L2: React SPA, FastAPI API process, SQLite store, committed data files (market snapshot, fund look-through, seeds, LLM recordings), LLM endpoint. C4 L3 for the API process: deterministic engine, Research & Insights, AI-on-Recommendations steps, Recommendations & Decisions, approvals policy, Grounding validator, audit chain, LLM Exchange capture, Assistant (incl. Screen Context), governance, config, health, auth/RBAC. Each component gets a responsibility line at navigation altitude. The tiered-approval policy is described exactly as the code applies it (Advisor always; Compliance on Suitability breach; Investment Committee when turnover or a single Trade Line crosses configured thresholds; re-plan on threshold change). Includes the Research Analyst UI.

**Blocked by:** 01

**Status:** resolved

- [x] C4 L2 and L3 Mermaid diagrams render under `check`
- [x] Responsibility table for every component; no file paths beyond top-level orientation
- [x] Tiered-approval description verified against the approvals policy and its tests
- [x] Only built behaviour described; `check` green

## Comments

**2026-11-08, implementation (Claude).**
- §5.1 is the C4 L2 container view: SPA, API process, operator scripts, SQLite, committed data files, LLM endpoint, Twelve Data. §5.2 is the C4 L3 view of the API process: 15 components, each with one responsibility row and one entry point (a module or an HTTP prefix). §5.3 lists the SPA screens, including the Research Analyst UI.
- The tiered approval policy is in §5.2 under "Tiered approval policy". It was checked against `app.approvals`, `app.recommendations` and `tests/test_approvals.py`. One claim, that lowering a threshold adds the Committee step before the Recommendation reaches it, followed from the code but had no test. `test_lowering_thresholds_before_the_committee_step_adds_it` now covers it. I confirmed the test fails when the re-plan is sabotaged.
- Diagram edges follow the real import graph. The audit chain points at Exchange capture because chain verification recomputes Exchange hashes.
- Config literals (threshold defaults, TTL, ports) are left out on purpose. They belong in the generated config region (ticket 07).
- Review fixes, Standards: no per-module lists or file names, Claim capitalised, "outside its Tolerance Bands". Review fixes, Spec: the reversed or missing edges, the recordings directory wording, and the Assistant making "at most one" LLM call.

**Verified:** `architecture_doc check` OK with Mermaid rendering on; full pytest 630 passed, 1 skipped (before the new test), then `test_approvals.py` and `test_architecture_doc.py` 48 passed; ruff clean.
