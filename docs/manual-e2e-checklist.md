# Manual E2E checklist (one page)

Detail for each step: `docs/manual-e2e-guide.md`. Tick as you go.

## Setup

- [x] `source .venv/bin/activate`
- [ ] `uv run python -m app.seeder` and `uv run python -m app.research_seed`
- [ ] `uv run uvicorn app.main:create_app --factory --port 8000`
- [x] `cd frontend && npm run dev` -> <http://localhost:5173>
- [x] Log in with username = role name (`advisor`, `compliance_officer`, ...) and the `APP_SEED_USER_PASSWORD` password
- [x] LLM mode known: live (AI steps work) or recorded (AI steps show "failed", rest still works)

## Advisor: queue (C001-C005 are the planted scenarios)

- [x] Nav shows no Audit, Governance or Config
- [x] Run analysis; all 25 portfolios scored

## Advisor: Run Analysis modal

- [ ] Run analysis opens the modal at once, listing Load inputs, Score Portfolios, Record run, Priority narratives, Recommendation narratives
- [ ] Each Run Step goes pending -> running -> done with its time; the active one has a ticking timer; the header total keeps counting
- [ ] Score Portfolios counts up `n/25`
- [ ] Steps tick to done without polling: DevTools Network shows one `events` request (EventStream) and no repeated `/api/analysis/runs/<id>` requests
- [ ] Restart the API mid-watch: the modal shows "Reconnecting…" (or, behind the Vite dev proxy, "Live updates unavailable; checking every 1s"), then goes live again on its own once the API is back (no reload)
- [ ] Stream refused (any non-200 on `events`): the modal shows "Live updates unavailable; checking every 1s" and keeps updating by polling the snapshot; if polling fails too (e.g. session cookie cleared) it shows "Could not load the run's progress. Retrying…"
- [ ] Without an LLM configured, both narrative steps show skipped and the run ends Completed
- [ ] On Completed the Queue behind refreshes (new run number in the subtitle); View updated queue closes the modal on it
- [ ] Completed with warnings, recorded LLM mode: with approved research in place (`uv run python -m app.research_seed`), move every `data/llm_recordings/priority_narrative-*.json` aside, then Run analysis. Priority narratives shows failed with "Narrative unavailable (AI step failed; scores are unaffected).", Recommendation narratives still runs and shows done, the header reads "Completed with warnings", the Queue refreshes to the new run and View updated queue is offered. Put the recordings back
- [ ] Interrupted: with approved research in place and a live LLM (so the run is slow), Run analysis, then stop the API (Ctrl-C) during Score Portfolios and start it again. Reload the Queue: no pill, Run analysis is enabled and the Queue still shows the previous run number. Open `/api/analysis/runs/<id>` for the stopped run: `"outcome": "interrupted"`, every step `skipped`. A modal left open on the stopped run (stale tab) ends on "Interrupted" with "Run interrupted. The Queue still shows the previous run" and the Queue does not refresh. Run analysis again: a new run starts at once. (If the stop lands after Record run, the stopped run shows Load inputs, Score Portfolios and Record run done, the narratives skipped, and the Queue shows that run)
- [ ] The modal header reads "Started by advisor at <time>" for your own run
- [ ] Close and reopen (use a live LLM, or approved research in place, so the run is slow): Close (or Escape) mid-run; the header shows "Analysis running… View progress" and Run analysis reads "Analysis Run in progress". Either one reopens the modal on the same run, which has kept going (the steps moved on while it was hidden). Close it again and let the run finish: the pill goes, the button reads Run analysis again, and the Queue refreshes to the new run number without the modal open
- [ ] Reload mid-run: reload the Queue page during Score Portfolios. The modal comes back on its own on the same run number, with the pill behind it. Go to another page and back to the Queue mid-run: same. Reload once the run has finished: no modal, no pill
- [ ] A second user attaches: in a private window log in as `relationship_manager` and open the Queue. As `advisor`, start a run. Reloading the private window shows the pill and the modal ("Started by advisor at <time>"). Or, from a Queue tab opened before the run started, click Run analysis: no new run starts (same run number), the modal reads "A run was already in flight, so this one is shown instead of starting another" and "Started by advisor at <time>"
- [ ] Focus lands in the modal and Tab stays inside; Escape hides it; focus returns to Run analysis
- [ ] With "reduce motion" on in the OS, the running indicator is a still ring, not a spinner
- [x] Score 0-100, High/Medium/Low label, 4-part breakdown, SLA flag, cited narrative
- [x] Filter by label and risk profile; sort by review-due
- [x] C001-C004 rank above C005; C005 is Low

## Advisor: drill-down and recommendation (C001)

- [x] Holdings, actual vs target, drift vs tolerance bands, one Portfolio Drift number
- [x] Risk profile, horizon, liquidity, restrictions shown
- [x] Look-through sector exposure includes tech held via ETFs
- [ ] Insights with report-page citations
- [ ] Proposed vs allowed Research Tilt (+-2 pp)
- [ ] Trade Lines in % and currency
- [ ] Rationale cited; ungrounded claims flagged and kept out of the memo; memo present
- [ ] Suitability results show rule ID and numbers
- [ ] "Approved = cleared to act outside this system" is clear
- [ ] `relationship_manager` sees masked client fields; `advisor` sees them

## Approvals

- [ ] C002/C003 (no breach, not high-impact): Advisor accept -> Approved
- [ ] Modify Trade Lines -> new linked version, suitability re-run, breach warning shown
- [ ] C004: Advisor accept -> Pending Compliance
- [ ] Compliance sees rule ID, limit, actual, Trade Line, warnings, restrictions, grounding flags
- [ ] Compliance approve without rationale is refused; with rationale works; block works
- [ ] Compliance cannot act before the Advisor has decided
- [ ] High-impact (turnover >= 15% or line >= 10%) reaches Investment Committee with thresholds visible
- [ ] Committee approve/reject needs a rationale

## RBAC

- [ ] Advisor opening `/audit` or `/governance` gets no view
- [ ] Forbidden API calls return 403 (e.g. `GET /api/config` as `relationship_manager`, `POST /api/analysis/runs` as `auditor`)

## Auditor

- [ ] Audit search by type, actor, client, date; `access_denied` events present
- [ ] Overrides highlighted; AI events show model and prompt version; seed items show human-verified
- [ ] Lineage: report passage -> insight -> tilt -> recommendation -> decisions
- [ ] Verify chain reports OK
- [ ] Governance: model card, prompt log, AI quality panel
- [ ] Adversarial fixtures (fabricated quote, wrong number, uncited call) flagged or blocked

## LLM Exchanges

- [x] `auditor`, `compliance_officer`, `platform_owner` see "LLM Exchanges" under GATEWAY; `advisor` and `relationship_manager` do not, and `/llm-exchanges` shows no page for them
- [ ] Feed lists newest first: time, task, prompt version, model, live/recorded pill, outcome, latency, tokens, linked Recommendation or Portfolio; figures right-aligned in monospace
- [ ] Filters work alone and combined: task, prompt version, mode, outcome, date range
- [ ] Recorded (replayed) rows show tokens and latency as "n/a (replayed)"; failed rows are marked and show the error summary
- [ ] Empty database shows the empty state; a filter with no hits shows "No Exchanges match"; stopping the API shows the error line
- [ ] Live tail on, then Run analysis (Queue page, another tab): new Exchanges appear without reloading, each once
- [ ] Live tail off: rows already shown stay; the list catches up on anything missed
- [ ] Stop the API while tailing: pill goes to "Reconnecting…"; restart it and the tail resumes with nothing missing or doubled
- [ ] Tail refused (e.g. session expired) falls back to the list with "Stream unavailable, showing list" and no rows lost

### Exchange drawer, download and lineage entry

- [ ] Click a feed row (or its # button): a drawer opens with Prompt, Schema, Reply, Metadata and Used by tabs; Escape and a click on the scrim both close it
- [ ] Prompt shows system text and user prompt; long content scrolls inside the drawer and the page behind does not clip it
- [ ] Reply shows the raw text and the parsed view; a reply with ungrounded Claims shows them flagged in red, with the tab marked
- [ ] Metadata shows hash, tokens, latency, model, endpoint host and mode; a recorded Exchange shows "n/a (replayed)" for tokens and latency
- [ ] Used by lists the referencing Audit Events and the grounding verdict, and links to the Recommendation's lineage
- [ ] "Download JSON" saves `llm-exchange-<id>.json` containing the Exchange and its `hash`
- [ ] A failed Exchange shows the error text and any raw reply that was captured
- [ ] Lineage page, as a role with `llm:read`: AI nodes show "View LLM Exchange" and open the same drawer; as a role without `llm:read` the button is absent

### Advisor AI-step summary

- [ ] `advisor`: a Recommendation's AI contribution lists each AI step (Research Tilt, Rationale and memo) with a live or recorded pill, ok or failed, latency and grounded/ungrounded counts in monospace; no prompt or reply text and no "Open exchange" button
- [ ] Recorded mode: latency reads "n/a (replayed)"; steps with no recording show `failed` with a short reason, and the plain rule-based Recommendation is unaffected
- [ ] `relationship_manager`: same summary, client name and email still masked
- [ ] `compliance_officer` (Portfolio page): steps also show "Open exchange", which opens the Exchange drawer

## Research Analyst

- [ ] Sign-in screen offers Research Analyst; logging in as `research_analyst` lands on the Research screen's To review tab (URL `/research`), not the "Select a section" placeholder, even when the tab was left on another role's page (e.g. `/queue`)
- [ ] Nav shows a single Research item under RESEARCH; it opens on the To review tab (`/research`), with Reports as the second tab (`/research/reports`); the Research nav item stays active on both and on Report detail
- [ ] On the Reports tab, the table lists the 5 seeded Reports, newest first, each with title, kind (PDF/Text), page count, uploader, upload time (UTC), extraction outcome and Awaiting review / Approved / Rejected counts that add up to the Report's Insights
- [ ] Every seeded Report carries a "Human-verified seed" badge and a "Seeded" outcome
- [ ] Failed extraction (with `APP_LLM_MODE=recorded`, upload any new `.txt`, which has no recording): the Report shows a red "Extraction failed" pill with an alert icon and text (hover shows the stored error), and its row is marked
- [ ] Throttle the network (DevTools, Slow 3G) and reload: skeleton rows show while the list loads; stop the API and reload: an error line says "Could not load Reports"
- [ ] `advisor` and `auditor`: no Research item in the nav, and opening `/research` or `/research/reports` shows the placeholder, not a Research tab
- [ ] Open a seeded Report (click its row or title, e.g. the Q2 research update): the header shows title, ID, kind, page count, uploader, upload time (UTC), "Seeded" and "Human-verified seed"; a "Reports" link returns to the library (`/research/reports`)
- [ ] The Insight list is in page order (then ID); each row shows subject, page, direction, confidence and status pills; the first Insight is selected
- [ ] The detail pane shows the subject with its kind (Sector or Asset Class), direction and confidence pills, "Cited on page N", the cited passage, and a read-only Insight Review record at the top (Approved, reviewer `seed`, time, note) with a "Human-verified seed" marker and no Approve or Reject; nowhere does the UI say "decide" or "Decision"
- [ ] The cited page shows in full with the passage highlighted and scrolled into view inside the page box (try an Insight whose passage is low on a long page); the page header carries a "Cited page" pill
- [ ] Switch page with the picker and the previous/next buttons: other pages show unhighlighted and "Back to cited page N" returns; reselecting an Insight returns to its cited page
- [ ] Passage-not-found warning: in DevTools, override the response of `GET /api/reports/{id}/pages/{n}` with text missing the passage (or wait for an uploaded Report in ticket 03 whose passage is edited): the page shows unhighlighted with "Cited passage not found verbatim on page N"
- [ ] Filter by status: Awaiting review / Approved / Rejected / All with counts; Awaiting review on a seeded Report shows "No Insights in this Report are awaiting review."; reload keeps the filter (`?status=` in the URL)
- [ ] Select an Insight, then reload: the same Insight and page come back (`?insight=` in the URL); copy the URL into a new tab, same result
- [ ] `/research/reports/NOPE` shows "Report not found"; `?insight=9999` on a real Report shows "Insight #9999 is not in this Report" with "Show the first Insight"
- [ ] At 1280px and wider the Insight list and the detail sit side by side; narrower, the list stacks above the detail
- [ ] A Report whose extraction failed shows the stored error in red and "No Insights, because extraction failed"; a Report that succeeded with none shows the neutral "No Insights were extracted from this Report" with its page count; both still let you read their pages
- [ ] Throttle the network and open a Report: skeletons for the header, list and page text; stop the API and pick an unloaded page: "Could not load page N of this Report"
- [ ] Upload setup: start the API with `APP_LLM_MODE=recorded APP_LLM_RECORDINGS_DIR=tests/fixtures/llm`, where the committed extraction recordings live (`data/llm_recordings/` is gitignored, and a stale local recording there can replay an empty extraction)
- [ ] `research_analyst` sees an Upload Report button in the Research header; `advisor` and `auditor` never reach the screen; nothing else shows it
- [ ] Upload Report: focus moves into the dialog on "Choose a file"; Tab and Shift+Tab cycle inside it; Escape, Cancel, the close button or a backdrop click close it and focus returns to Upload Report
- [ ] Upload the demo house view (`tests/fixtures/house_view_demo.txt`), picked and then again by drag and drop (the zone highlights on drag-over): the file name and size show, the title placeholder is the file name; Upload and extract shows "Extracting Insights from your Report…" with every control disabled, and Escape or a backdrop click does nothing; it then closes and lands on the new Report's detail with 3 Insights awaiting review (Information Technology, Utilities, equity), and the Reports tab lists it newest first with Awaiting review 3
- [ ] A typed title replaces the file name as the Report's title; an empty one keeps the file name
- [ ] Unsupported type (e.g. a `.docx` or `.png`): rejected in the dialog with "… is not a PDF or text file", and DevTools Network shows no `POST /api/reports`
- [ ] Over 20 MB (`head -c 21000000 /dev/zero > big.txt`): rejected in the dialog with "big.txt is 20.03 MB, over the 20 MB limit", no request sent
- [ ] Server refusals stay inline: an empty or non-UTF-8 `.txt`, or a `.pdf` that is not a PDF, shows the server's 422 message in the dialog; picking another file clears it and the upload can be retried without reopening
- [ ] Failed extraction: upload a `.txt` with no recording (any new text): lands on its detail with "Extraction failed: No recorded response for insight_extraction …" and an Upload again button, which reopens the dialog and returns focus to it on close
- [ ] Review setup: upload the demo house view (above) so its Report has 3 Insights awaiting review; open it with the Awaiting review filter
- [ ] Only an Insight awaiting review shows Approve and Reject…, at the top of the detail pane, with copy beside them saying an Insight Review is final; approved and rejected Insights show the read-only record there instead. Neither appears for any other role (the server also answers 403 to `POST /api/insights/{id}/decision` from `advisor`)
- [ ] Approve without a note: the button reads "Saving…" and both actions disable while the request runs (double-clicking sends one `POST …/decision` in DevTools Network); the Insight's row turns Approved, the filter counts and the Reports tab's Awaiting review count drop at once (before the refetch lands), a notice says "Approved Information Technology (Insight #N). Showing the next Insight awaiting review.", and the selection moves to the next Insight awaiting review in page order
- [ ] Approve with a note: "Approval note (optional)" is collapsed; expanding it shows a note field; approving records the note, and selecting that Insight again shows it in the read-only record with reviewer `research_analyst` and the time
- [ ] Reject requires a note: Reject… opens a dialog with the note focused; "Reject Insight" stays disabled while the note is empty or only spaces; Tab and Shift+Tab stay inside; Escape, Cancel, the close button or a backdrop click close it without a request and focus returns to Reject…
- [ ] Reject a mis-tagged Insight with a note saying what was wrong (e.g. "Direction should be negative: the passage says limited upside"): it turns Rejected and its record shows the note; it never appears among an Advisor's Insights
- [ ] When the last Insight awaiting review is reviewed, the selection stays on it (now read-only with its outcome, reviewer, time and note) and the detail says "This Report is fully reviewed"
- [ ] 409 race: open the same Report and Insight awaiting review in two browser sessions (a normal and an incognito window, both `research_analyst`); approve in one, then approve or reject in the other: a non-blocking notice says "Already reviewed by someone else…", the Insight refreshes to the first session's outcome, and the selection advances; nothing is recorded twice on the audit trail
- [ ] Other failures: stop the API and approve: an inline error in the detail pane says the Insight Review was not saved, and the selection stays; a failed reject keeps its note, so reopening Reject… shows it for a retry
- [ ] To review on a fresh database (seeded only, nothing uploaded): the tab shows "All caught up" with a check, Upload Report and Browse Reports, and the To review badge reads 0. It is plainly different from loading (throttle and reload: skeletons) and from an error (stop the API and reload: the red "Could not load Reports" line)
- [ ] Upload the demo house view, then open To review: one group for it, with its title (a link to its Report), uploader `research_analyst`, upload time (UTC) and "3 to review"; its 3 Insights are in page order, without status pills, and the first is selected. The badge reads 3, matching the Reports tab's Awaiting review count. Upload it again: the newer copy's group comes first and the badge reads 6
- [ ] Selecting an Insight shows "From <Report title>" above the same detail, cited page and highlight as Report detail; `?insight=` is in the URL (`&page=` too while another page is read), and a reload or the URL in a new tab restores it
- [ ] Approve and reject from To review behave as on Report detail (optional approval note, required reject note, "Saving…", inline errors, the 409 notice across two sessions; a 409 on the last Insight awaiting review keeps it selected and, once refreshed, shows the other session's Insight Review read-only, with no Approve or Reject); the Insight leaves the list, and the group count, the badge and the Reports tab's count drop at once; the selection moves to the next Insight in inbox order, into the next group after a group's last Insight
- [ ] Reviewing the last Insight of a group removes the group; reviewing the last one overall shows "All caught up" with the notice above it, the badge reaches 0, and the URL has no `?insight=`
- [ ] `/research?insight=9999` shows "There is no Insight #9999" with "Show the first Insight awaiting review"; a link to an Insight reviewed since (e.g. a seeded one) opens it read-only with "This Insight is no longer awaiting review"

## Supersession and clean portfolio

- [ ] Rerun analysis: open recommendations become Superseded
- [ ] C005 still produces no action

## API-only roles (curl or <http://localhost:8000/docs>)

- [ ] `research_analyst`: upload report; insights pending; approve via `/api/insights/{id}/decision`
- [ ] `platform_owner`: `GET /api/health`; `PATCH /api/config` changes the next run
- [ ] `portfolio_manager`: read-only

## Optional

- [ ] Tamper with a copy of `data/app.db`; Verify chain names the first broken link

## Notes

- Live mode costs money and the first run is slower (one LLM call per portfolio narrative)
- Config and Health nav items hit the placeholder page (no routes in `main.tsx`)
- README says Anthropic is the default provider; confirm `.env` is intentional
