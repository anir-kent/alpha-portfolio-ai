# 01: Prefactor: the Analysis Run reports Run Steps through an optional reporter; tests start runs through `run_and_wait`

**What to build:** Nothing changes for users. This ticket prepares the code so the run can move to the background without a wide test change. The Analysis Run accepts an optional progress reporter and tells it when each of the five Run Steps (`load_inputs`, `score_portfolios`, `record_run`, `priority_narratives`, `recommendation_narratives`) starts, finishes, is skipped or fails, and updates the Portfolio count after each Portfolio is scored. The command-line run passes no reporter. Every existing test that starts an Analysis Run through the API does so through one shared `run_and_wait` helper, which for now just checks that the start succeeded. Ticket 02 then makes the run asynchronous by changing only that helper. See the spec at `.scratch/run-analysis-progress/spec.md` and ADR-0005.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] The Analysis Run accepts an optional progress reporter; with none, behaviour, return value and Audit Events are exactly as today
- [x] With a reporter, a test run reports the five Run Steps in order. Score Portfolios reports `done`/`total` after each Portfolio. With no LLM, both narrative steps are reported as skipped
- [x] Run Step keys and labels are defined once and shared, ready for the API snapshot
- [x] Every existing test that starts a run through the API uses `run_and_wait`; no test checks the start status code directly any more
- [x] The command-line analysis run and the seeder work unchanged
- [x] Full test suite green; no Audit Event payload changes
