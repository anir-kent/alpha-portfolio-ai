# 04: Failure outcomes: Failed and Completed with warnings

**What to build:** The modal tells the truth when things go wrong.
- **Scoring breaks** (Load inputs, Score Portfolios or Record run): the run ends **Failed**. Nothing from it is kept, and the previous Analysis Run stays current. The modal marks the failed Run Step, shows the steps after it as skipped, and shows a safe message: "<Step> failed. The Queue still shows the previous run. Reference: run #<id>". The full traceback goes to the server log, keyed by run id.
- **An AI narrative step fails after the results were recorded:** the run ends **Completed with warnings**. The new results are current, and the failed step uses the existing "AI step failed" wording.

See the spec at `.scratch/run-analysis-progress/spec.md`.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Broken market data (through the existing dependency override) makes Score Portfolios fail. The snapshot shows `failed` with that step failed and later steps skipped, and the error is a fixed safe message with no exception text
- [ ] A Failed run leaves no Priority Results, Suitability results, Recommendations or Audit Events, and does not supersede any open Recommendation. The Queue still serves the previous run
- [ ] A failed run's row keeps its outcome and Run Step results, and the traceback is logged with the run id
- [ ] A fake LLM that raises during the narrative steps gives `completed_with_warnings`. The Queue moves to the new run and the failed narrative step carries the "AI step failed" wording
- [ ] After a Failed run, a new run can start straight away
- [ ] The modal shows the Failed and Completed with warnings states with the agreed wording. Only Completed with warnings refreshes the Queue and Recommendation queries and offers View updated queue
- [ ] `npm run typecheck` and `npm run build` pass; the manual E2E checklist gains an item for Completed with warnings in recorded LLM mode
