# 06: Leaving and coming back: close/reopen, reload, attaching to a colleague's run

**What to build:** A run outlives the modal. Closing it (Close or Escape) only hides it; the run continues. While a run is in flight, the Queue header shows an "Analysis running… View progress" pill that reopens the modal. Reloading the Queue page mid-run brings the modal back on its own. While a run is in flight, the Run analysis button opens that run instead of starting another. When a colleague starts a run first, clicking Run analysis attaches the modal to their run and shows "Started by <name> at <time>". See the spec at `.scratch/run-analysis-progress/spec.md`.

**Blocked by:** 02

**Status:** done

- [x] Closing the modal never stops or changes the run
- [x] On load, the Queue page asks for the current run. If one is in flight it shows the pill and reopens the modal; when idle it shows neither
- [x] The pill disappears once the run has an outcome, and the Queue refreshes on Completed or Completed with warnings even if the modal is closed
- [x] While a run is in flight, Run analysis is labelled to show this and opens the modal for that run
- [x] A `409` on start attaches the modal to the returned run, with the actor name and start time in the header
- [x] The modal header always shows who started the run and when
- [x] `npm run typecheck` and `npm run build` pass; the manual E2E checklist gains items for close and reopen through the pill, reloading mid-run, and a second user attaching

## Comments

- Done on `feature/run-analysis-progress`. Frontend only: the backend contract (`current` 200/204, `409` with the run's snapshot and `actor_name`) was already in place and tested by tickets 02 and 03. There is no frontend test runner (spec), so it is checked by `npm run typecheck`, `npm run build` and the manual E2E checklist.
- `useRunProgress` follows the run (stream, poll fallback, Queue and Recommendation refresh) from the Queue page, not from inside the modal, so hiding the modal changes nothing. The modal only shows what it is given. This removes ticket 02's leftover where closing the modal mid-run lost the Queue refresh.
- The Queue page asks `current` once per visit (`gcTime: 0`, no refetch on focus); a run found in flight opens the modal on its own. Following then goes over the run's own stream. Leaving the Queue page stops following; coming back asks `current` again.
