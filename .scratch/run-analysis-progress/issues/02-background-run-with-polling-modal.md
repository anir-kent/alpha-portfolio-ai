# 02: Start an Analysis Run in the background and follow its Run Steps in a polling modal

**What to build:** The end-to-end tracer bullet. An Advisor clicks **Run analysis** on the Queue and a modal opens at once, listing the five Run Steps. Each step moves from pending to running to done (or skipped, when no LLM is configured), with how long it took, a running timer on the active step, the `n/N` Portfolio count on Score Portfolios, and the total time in the header. The modal updates by polling the run's snapshot. When the run is Completed, the Queue and Recommendation views refresh and the modal offers **View updated queue**.

Behind it:
- The run starts on a background thread, with only one Analysis Run in flight at a time.
- Progress is kept in the in-memory registry (ADR-0005).
- The Analysis Run row is committed before scoring starts and records its outcome and Run Step results at the end.

API contract, schema and modal behaviour are in the spec at `.scratch/run-analysis-progress/spec.md`.

**Blocked by:** 01

**Status:** done

- [x] The Analysis Run table gains outcome, finished-at and Run Step results. The existing `completed` flag and the Queue's "latest completed run" query are unchanged
- [x] `POST /analysis/runs` commits the run row, starts the run in the background and returns `202` with the snapshot. While a run is in flight it returns `409` with that run's snapshot
- [x] `GET /analysis/runs/{id}` serves the in-flight state from the registry, or the stored result once the run has finished. Unknown ids get `404`
- [x] `GET /analysis/runs/current` returns the in-flight snapshot, or `204` when idle
- [x] All three endpoints require `analysis:run`; denials get `403` and are audited like other denials
- [x] `run_and_wait` polls the snapshot until there is an outcome, and the existing tests pass with only that change
- [x] API tests: with a blocking fake LLM, a run frozen mid-way shows the earlier steps done and the active one running, with `done`/`total`. After release it ends Completed. Without an LLM, the narrative steps are skipped and the run is Completed
- [x] The Queue result and the run's Audit Events are identical to what the synchronous run produced
- [x] The modal is an accessible dialog: focus moves inside and returns to the trigger, Escape hides it, the step list is a polite live region, and the running indicator respects reduced motion
- [x] On Completed the Queue and Recommendation queries refresh, and View updated queue closes the modal on the refreshed Queue
- [x] The frontend API types are regenerated; `npm run typecheck` and `npm run build` pass
- [x] The manual E2E checklist gains items for starting a run and watching the steps complete

## Comments

- Done on `feature/run-analysis-progress`. Backend: `app/analysis_runs.py` (registry, snapshot reporter, one-in-flight runner); `run_analysis(run_id=...)` uses the row committed by `open_run`. Tests: `tests/test_analysis_runs.py` (HTTP seam), and only `tests/runs.py` changed for the existing suite.
- An existing database gets the outcome columns on startup, and its completed runs are marked `completed`. CLI and seeder runs also record `completed`, so ticket 05's startup sweep will not mark them interrupted.
- The frozen-run test seeds approved research, so the blocking LLM freezes a Research Tilt *inside* Score Portfolios (`done < total`). A login during a run blocks on SQLite's write lock (spec Further Notes), so tests log users in before a run starts.
- Left for later tickets: a safe per-step error message (04). The Queue refresh lives in the modal, so it does not happen if the modal is closed mid-run (06 must move it out). If the final save of the outcome fails, the registry shows the outcome but the row has none (05's sweep will then call it interrupted).
