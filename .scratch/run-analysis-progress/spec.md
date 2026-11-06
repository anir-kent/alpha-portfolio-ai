Status: ready-for-agent

# Run Analysis progress: a modal that follows each Run Step of the Analysis Run live

Vocabulary follows `GLOSSARY.md` (new terms: **Analysis Run**, **Run Step**). Decisions respect `docs/adr/0001` to `0004` and the new `0005-run-step-progress-in-process`.

## Problem Statement

When an Advisor or Relationship Manager clicks **Run analysis** on the Queue, the button changes to "Running…" and the page waits, with no sign of what is happening, for as long as the Analysis Run takes. With a live LLM that can be a long time, because the run asks for a Research Tilt for each Portfolio and then writes priority and Recommendation narratives. The user cannot tell whether the run is stuck, which stage it is at, or how many Portfolios are scored. If they leave or reload the page, the button is enabled again and nothing shows that a run is still going. A second click from another user starts a run that competes for the same database. When the AI steps fail, the run still succeeds, but the screen does not say so. When the run itself fails, the user only sees a generic request error.

## Solution

Clicking **Run analysis** starts the Analysis Run in the background and opens a **Run Analysis modal** at once. The modal lists the Run Steps in order:

1. Load inputs
2. Score Portfolios (with an `n/N` count)
3. Record run
4. Priority narratives
5. Recommendation narratives

Each Run Step shows its outcome (pending, running, done, failed or skipped), how long it took, and a running timer while it is the active step. The backend pushes each change over a live stream, so a Run Step shows as done within about a second of the backend finishing it.

The modal ends in one of four Analysis Run outcomes:

- **Completed**
- **Completed with warnings**: an AI step failed after the results were recorded, and the new results are still current.
- **Failed**: nothing changed, and the previous run is still current. The modal shows a safe message and a run reference.
- **Interrupted**: the server restarted mid-run.

On Completed and Completed with warnings, the Queue refreshes and the modal offers **View updated queue**.

Only one Analysis Run can be in flight. Clicking Run analysis while another run is going attaches the modal to that run and says who started it and when. Closing the modal never stops the run. A pill in the Queue header ("Analysis running… View progress") reopens it, and reloading the page brings it back on its own. There is no Cancel.

## User Stories

1. As an Advisor, I want clicking Run analysis to open a progress modal at once, so that I know my click was accepted.
2. As an Advisor, I want to see every Run Step of the Analysis Run listed in order before it starts, so that I know what the run will do.
3. As an Advisor, I want the active Run Step marked as running, so that I can see where the run is.
4. As an Advisor, I want each Run Step marked done as soon as the backend finishes it, so that the screen matches what really happened.
5. As an Advisor, I want to see how many Portfolios have been scored out of the total, so that I can judge progress through the longest step.
6. As an Advisor, I want to see how long each finished Run Step took, so that I can tell which stage is slow.
7. As an Advisor, I want a running timer on the active Run Step and a total time in the header, so that I can see the run is still moving.
8. As an Advisor, I want the AI narrative steps shown as skipped when no LLM is configured, so that I do not think something failed.
9. As an Advisor, I want a clear "Completed" result when every Run Step is done, so that I know the Queue reflects the new run.
10. As an Advisor, I want "Completed with warnings" when an AI narrative step fails after the results were recorded, so that I know the scores are new but some narratives are missing.
11. As an Advisor, I want a failed AI step described in the same "AI step failed" language used elsewhere, so that the wording is consistent.
12. As an Advisor, I want a clear "Failed" result naming the Run Step that failed, so that I know the run did not change the Queue.
13. As an Advisor, I want a failed run to tell me the previous run is still current, so that I can keep working from it.
14. As an Advisor, I want a failed run to show a run reference instead of a technical error, so that I can report it without seeing internals.
15. As a platform owner, I want the full error of a failed run in the server log, keyed by the run id, so that I can find it from the reference a user gives me.
16. As an Advisor, I want the Queue refreshed on its own when the run completes, so that I do not have to reload.
17. As an Advisor, I want a View updated queue action at the end of a successful run, so that I can go straight to the new ranking.
18. As an Advisor, I want my open Recommendation views refreshed after a run, so that I do not act on a superseded Recommendation.
19. As an Advisor, I want to close the modal without stopping the run, so that I can keep reading the Queue while it works.
20. As an Advisor, I want a pill in the Queue header while a run is in flight, so that I can reopen the progress after closing it.
21. As an Advisor, I want the modal to reappear when I reload the page during a run, so that I do not lose track of it.
22. As an Advisor, I want the Run analysis button to show that a run is already in flight, so that I do not try to start a duplicate.
23. As a Relationship Manager, if I click Run analysis while a colleague's run is going, I want the modal to attach to their run, so that two runs never compete.
24. As a Relationship Manager, when I attach to a colleague's run, I want to see who started it and when, so that I understand why my click did not start a new one.
25. As an Advisor, I want the modal to recover on its own when my connection drops briefly, so that a network blip does not leave stale progress on screen.
26. As an Advisor, I want to see when the live connection is reconnecting, so that I know the progress shown may be briefly behind.
27. As an Advisor, I want an "Interrupted" result if the server restarted mid-run, so that I know to start a new run and that the previous results still stand.
28. As an Advisor, after an interrupted run, I want to be able to start a new run straight away, so that a crash never blocks my work.
29. As a keyboard user, I want focus moved into the modal when it opens and returned to the Run analysis button when it closes, so that I can use it without a mouse.
30. As a keyboard user, I want Escape to close (hide) the modal, so that it behaves like other dialogs.
31. As a screen reader user, I want Run Step changes announced politely, so that I hear progress without being interrupted constantly.
32. As a user who prefers reduced motion, I want the running indicator to respect that setting, so that the modal is comfortable to watch.
33. As a role without `analysis:run`, I want neither the button nor the progress endpoints available to me, so that access stays as it is today.
34. As an Auditor, I want the audit chain unchanged by this feature (no step-progress Audit Events), so that the chain still holds only business facts.
35. As an Auditor, I want the Audit Events of a completed run to stay exactly as they are today, so that lineage and chain verification keep working.
36. As a Compliance Officer, I want a failed or interrupted run to leave no business records behind, so that no partial scores or Recommendations ever appear.
37. As a platform owner, I want every Analysis Run attempt, including failed and interrupted ones, kept in the run history with its outcome and Run Step results, so that I can see how reliable runs are.
38. As a developer, I want the command-line analysis run to keep working with no progress reporting attached, so that scripts and seeding are unaffected.

## Implementation Decisions

**Analysis Run lifecycle (backend)**
- Starting a run becomes asynchronous. `POST /analysis/runs` checks for a run in flight. If there is one, it returns `409` with that run's snapshot. If not, it creates and commits the Analysis Run row (not completed, outcome unset) in its own short transaction, starts the run on a dedicated background thread with its own Session, and returns `202` with the run snapshot. The response model changes from today's `{run_id, portfolios_scored}` to the snapshot; the frontend's generated API types are regenerated.
- A process-wide lock admits only one Analysis Run in flight (ADR-0005). The "in flight" check consults the registry, so an interrupted row left in the database can never block a new run.
- The scoring work stays one transaction, exactly as today: Load inputs, Score Portfolios and Record run all commit together, and a failure in any of them rolls them all back. The narrative steps keep their current behaviour after the commit: a failure there cannot undo the run.
- The run function, `run_analysis`, gains an optional progress reporter parameter. It reports Run Step starts, finishes, failures and skips, and the Portfolio count after each Portfolio is scored. The command-line entry point passes nothing, which means a reporter that does nothing. Its return value and its Audit Events are unchanged.
- At the end, a final short transaction saves the outcome and the Run Step results on the Analysis Run row. On failure, the full traceback is logged with the run id, and the saved Run Step error is a safe, fixed message per step (e.g. "Scoring failed").
- On app startup, any Analysis Run row without an outcome is marked `interrupted`.

**Schema change**
- The Analysis Run table gains:
  - an outcome (`completed`, `completed_with_warnings`, `failed`, `interrupted`; null while in flight)
  - a finished-at timestamp
  - the Run Step results as JSON (a list of steps: key, label, outcome, started_at, finished_at, error, and for scoring the `done`/`total` count)
- The existing `completed` flag keeps its meaning (the results are recorded and this run can be current), so the Queue's "latest completed run" query is unchanged. A Completed with warnings run has `completed` true.

**Progress registry (in process)**
- A small module holds the state of the in-flight run, and the last finished one so that a modal opened just after the end still sees the result. It sits behind an interface: publish state, read the latest state with its sequence number. A broker can replace it later (ADR-0005). Updates are thread-safe, and each update bumps a sequence number for the run.

**API contract**
- `GET /analysis/runs/current`: the in-flight run's snapshot, or `204` when none.
- `GET /analysis/runs/{id}`: from the registry while the run is in flight, otherwise from the Analysis Run row. `404` if unknown.
- `GET /analysis/runs/{id}/events` (server-sent events): pushes a `progress` event whose data is the **full snapshot**, with the event id set to the sequence number for the run. It is sent on connect and on every change, combined at the existing stream poll interval. Keepalives use the same interval as the Exchange stream. The stream closes once the run has an outcome and the final snapshot has been sent. On reconnect, the latest snapshot is all the client needs; `Last-Event-ID` only avoids re-sending an unchanged snapshot. The stream frees its auth session the same way the Exchange stream does.
- Snapshot shape: run id, actor name, started_at, finished_at, outcome, and the ordered Run Steps (key, label, outcome, started_at, finished_at, error, and `done`/`total` where it applies).
- Run Step keys, fixed and ordered: `load_inputs`, `score_portfolios`, `record_run`, `priority_narratives`, `recommendation_narratives`. Steps 4 and 5 are `skipped` when no LLM is configured. When a run fails, the failed step is `failed` and the steps after it are `skipped`.
- All endpoints require `analysis:run`. Denied attempts are audited the same way as other denied requests.

**Frontend**
- Run Analysis modal: an accessible dialog (focus trap, initial focus, Escape hides it, focus returns to the trigger, `aria-live="polite"` on the step list, motion honours reduced-motion). It contains:
  - a vertical step list with an outcome icon and label, time taken or a running timer, and the `n/N` count on Score Portfolios
  - a header with the total time and who started the run and when
  - a footer whose actions depend on the outcome: Close always; View updated queue on Completed or Completed with warnings
- The live hook follows the Exchange stream hook's pattern: `EventSource` with credentials, connection states (connecting, live, reconnecting, unavailable), a fallback to the snapshot endpoint when the stream is refused or closed, and the latest snapshot replacing what is shown.
- Queue page: on load it asks `current`, and if a run is in flight it shows the "Analysis running… View progress" pill and reopens the modal. While a run is in flight, the Run analysis button opens the modal for that run. A `409` on start attaches to the returned run.
- When the run ends Completed or Completed with warnings, the client refreshes the Queue and Recommendation queries. Failed and Interrupted refresh nothing.
- Message wording: Failed shows "<Step> failed. The Queue still shows the previous run. Reference: run #<id>". A failed narrative step uses the existing "AI step failed" wording. Interrupted shows "Run interrupted. The Queue still shows the previous run".

**Audit**
- No new Audit Events. Run Step progress is telemetry (ADR-0005). A Failed run's `analysis_run_started` event rolls back with the rest. Failed and Interrupted attempts are recorded only on their Analysis Run row.

## Testing Decisions

- A good test drives the system from the outside, through the HTTP API, and checks what a user or client would see: status codes, snapshots, stream events, Queue contents and Audit Events. Tests must not reach into the progress registry, the reporter or thread internals.
- **Seam: the HTTP API**, the same seam as the existing Queue and LLM Exchange API tests. Timing and failure are controlled only through the dependency overrides the tests already use:
  - **LLM:** a fake that blocks on an event, to freeze the run mid-step; a fake that raises, for Completed with warnings; no LLM, for skipped narrative steps.
  - **Market data:** broken market data makes Score Portfolios raise, for Failed and rollback.
- A shared test helper, `run_and_wait`, starts a run and polls the snapshot until it has an outcome. Existing tests that start a run and then read results switch to it. The tests themselves stay the same.
- Behaviours to cover:
  - start returns `202` and a snapshot with all five Run Steps pending or running
  - the run ends Completed with every Run Step done, and the Queue matches what synchronous runs produce today
  - while frozen mid-step, the snapshot and the stream show the earlier Run Steps done and the active one running, with a `done`/`total` count
  - a second start while in flight returns `409` with the same run id
  - no LLM gives skipped narrative steps and Completed
  - a raising LLM gives Completed with warnings, and the Queue moves to the new run
  - broken market data gives Failed: no Priority Results, no Recommendations and no Audit Events from that run; the previous run still current; a safe error with no exception text
  - an outcome-less row plus an app restart gives `interrupted`, and a new run is accepted
  - stream: content type, a full snapshot on connect, one event per change, closing after the final snapshot, `Last-Event-ID` suppressing an unchanged re-send
  - `current` returns `204` when idle
  - permission: roles without `analysis:run` get `403` on every endpoint, and the denial is audited
  - the Audit Events of a completed run are unchanged
- Prior art:
  - the stream tests' `read_stream` helper, with a short poll interval and a short maximum stream duration
  - the Queue tests' seeding and login fixtures
  - the RBAC parametrised denial tests
- The command-line run is covered by the existing seeder and CLI tests continuing to pass.
- Frontend: there is no test runner. The modal is verified by `npm run typecheck` and by new lines in the manual E2E checklist:
  - open, watch the steps, close and reopen through the pill
  - reload mid-run
  - a second user attaches
  - completed with warnings in recorded LLM mode
  - keyboard and screen-reader basics

## Out of Scope

- Cancelling an Analysis Run.
- More than one API process or worker, and any external broker (Redis or similar). The registry interface leaves room for it (ADR-0005).
- Running more than one Analysis Run at once.
- An ETA or a percentage progress bar beyond the `n/N` count.
- A per-Portfolio progress list inside Score Portfolios.
- A run history page in the UI. Run history is only stored.
- Watching runs without `analysis:run`.
- Audit Events for Run Steps or for failed and interrupted attempts.
- Adding a frontend test runner.
- Changing how long the scoring transaction holds the write lock.

## Further Notes

- The scoring transaction still blocks other writers (Decisions, Insight approvals) while it runs, as it does today. This feature only makes that wait visible.
- ADR-0004's constraint (the run's Session is the only writer) is why progress is not written to the database while the run is in flight. Do not "fix" this by committing per step; that breaks the all-or-nothing run.
- The Exchanges page's live tail keeps working during a run and is unaffected. Both streams use the same poll interval setting.
