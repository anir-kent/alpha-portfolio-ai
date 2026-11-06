# 06: Leaving and coming back: close/reopen, reload, attaching to a colleague's run

**What to build:** A run outlives the modal. Closing it (Close or Escape) only hides it; the run continues. While a run is in flight, the Queue header shows an "Analysis running… View progress" pill that reopens the modal. Reloading the Queue page mid-run brings the modal back on its own. While a run is in flight, the Run analysis button opens that run instead of starting another. When a colleague starts a run first, clicking Run analysis attaches the modal to their run and shows "Started by <name> at <time>". See the spec at `.scratch/run-analysis-progress/spec.md`.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Closing the modal never stops or changes the run
- [ ] On load, the Queue page asks for the current run. If one is in flight it shows the pill and reopens the modal; when idle it shows neither
- [ ] The pill disappears once the run has an outcome, and the Queue refreshes on Completed or Completed with warnings even if the modal is closed
- [ ] While a run is in flight, Run analysis is labelled to show this and opens the modal for that run
- [ ] A `409` on start attaches the modal to the returned run, with the actor name and start time in the header
- [ ] The modal header always shows who started the run and when
- [ ] `npm run typecheck` and `npm run build` pass; the manual E2E checklist gains items for close and reopen through the pill, reloading mid-run, and a second user attaching
