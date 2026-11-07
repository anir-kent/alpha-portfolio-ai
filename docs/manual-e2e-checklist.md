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

## Assistant (Portfolio screen)

- [ ] The Assistant button shows next to the status strip for every role; it opens the drawer (`aria-expanded` true), the close button or Escape hides it and focus returns to the Assistant button, it stays open while moving between screens, and closing then reopening keeps the turns
- [ ] On `/portfolios/C001` the drawer header reads "Portfolio C001"; on a screen that publishes no context (e.g. a Recommendation's Lineage page) it reads "No context on this screen" and the Question box is disabled
- [ ] Ask "Which asset class drives the drift?" on C001: "Thinking…" shows, then the Answer renders as Markdown (bold, lists) with no raw HTML; follow-up questions fill the Question box when clicked
- [ ] Ask "Should I buy NVDA?": the fixed refusal shows ("I can only help with questions about this platform…"), never the model's text
- [ ] As auditor, the turn's LLM Exchange (task `assistant_answer`, `assistant_answer@v2`) is listed on LLM Exchanges with no Client name or email in its prompt, an `assistant.answered` or `assistant.refused` Audit Event references it, and Verify chain passes
- [ ] Ask two Questions on C001, then reload the page: reopening the drawer shows both turns in order
- [ ] Ask on C001, open `/portfolios/C002` and ask again: a "Context changed · Portfolio C002" divider separates the turns; the earlier turn still reads as asked on C001; a follow-up ("and why?") gets an Answer that uses the earlier turn (its Exchange prompt has a CONVERSATION SO FAR block with text only, no earlier Screen Context)
- [ ] Switch role (logout) and log back in: the drawer is empty, and the first Question is turn 1 of a new Conversation
- [ ] Ask "How far has C001 drifted?" on C001: the Answer lists its Claims with engine figure chips (e.g. `portfolio_drift_pp`); clicking one goes to `/portfolios/C001`. Report citation chips (`<report id> p.<page>`) open the quoted passage under the chip when clicked; a live model cites one from the Recommendation context (below)
- [ ] A Claim that failed grounding (e.g. a number the Screen Context doesn't hold) shows a red "ungrounded" marker in place with its reason below it, and the Claim stays in the Answer; as auditor, the turn's LLM Exchange shows the grounding verdict and a `claim_ungrounded` Audit Event names the `assistant_turn` subject
- [ ] Retry works: with the model unreachable (e.g. `APP_LLM_MODE=live` and a bad `APP_LLM_BASE_URL`, or a non-Suggested Question in recorded mode), ask on C001: the turn shows "The Assistant couldn't answer, try again." with no error detail and a Retry button. Fix the model, move to `/portfolios/C002` and click Retry: a new turn asks the same Question against C001 (a divider marks the context change back), the failed turn stays above it, and whatever is typed in the Question box is kept. As auditor, the failed turn has an `assistant.failed` Audit Event with `reason` `llm_error` that references the error LLM Exchange, and Verify chain passes

## Assistant (Queue and Recommendation screens)

- [ ] On `/queue` the drawer header reads "Queue"; ask "Why is C003 ranked above C005?": the Answer explains it from the priority components, and its engine chips (e.g. `queue.C003.score`) go to `/queue`
- [ ] Change the Queue's sort or filter and ask again: as auditor, the turn's Exchange prompt lists the rows in that order and filter; with `APP_ASSISTANT_CONTEXT_ROWS=10` it holds 10 rows and the note "showing 10 of 25", and the Answer says what it couldn't see
- [ ] Click a row's spark button on the Queue (`aria-pressed` true): the header reads "Queue, Portfolio C0xx"; click it again to clear it
- [ ] On a Portfolio with a Recommendation (e.g. C003 after approving the demo house view's equity Insight and running an analysis), the drawer offers "Portfolio C003" and "Recommendation N" to switch between; with the Recommendation chosen, ask "Which Report passage drove the tilt?": the Answer cites the passage with a Report chip that opens it
- [ ] Click a Trade Line's spark button: the drawer switches to "Recommendation N, Trade Line k" and "Why this one?" is answered about that line; clicking it again goes back to "Recommendation N"
- [ ] As auditor, that turn's Exchange prompt shows the Report passages after the JSON, between `<<<REPORT_PASSAGE …>>>` and `<<<END_REPORT_PASSAGE>>>` fences under an "untrusted data" heading, and no Client name or email anywhere
- [ ] Roles without `insight:read` (e.g. investment_committee) get no Insights or Report passages in a Recommendation prompt; they reach no Recommendation screen, so `tests/test_assistant.py` covers it

## Assistant (Approvals, Audit, LLM Exchanges, Governance, Config and Health screens)

- [ ] The drawer opens, closes and persists across navigation: open it on `/queue`, move through Approvals, Audit, Governance, LLM Exchanges, Config and Health (as the roles that see them); it stays open, its header follows each screen ("Approvals", "Audit", "Governance", "LLM Exchanges", "Config", "Health"), the turns stay, and closing then reopening keeps them
- [ ] As investment_committee, after the Advisor accepts C003 (high-impact): on `/approvals` ask "What is waiting on me?"; the Answer names C003's Recommendation and its status. Click the item's spark button: the header reads "Approvals, Recommendation N"; click again to clear it
- [ ] As auditor on `/audit`, search for Portfolio C003 and ask "What happened to this Portfolio?": the turn's Exchange prompt holds only C003's events, newest first (at most `APP_ASSISTANT_CONTEXT_ROWS`, with a "showing N of M" note when cut). A row's spark button makes the header "Audit, Event N"
- [ ] As auditor on `/llm-exchanges`, open an Exchange: the header reads "LLM Exchange N"; ask "What did the model see?": the new turn's Exchange prompt holds the opened Exchange's system text, prompt and reply fenced between `<<<LLM_EXCHANGE ...>>>` and `<<<END_LLM_EXCHANGE>>>`. Closing the Exchange returns the header to "LLM Exchanges", and the prompt then carries no Exchange body
- [ ] As platform_owner on `/governance`, ask "Which model and prompt versions are in use?": the Answer matches the model card
- [ ] As platform_owner on `/config` and `/health`, ask "How does an Analysis Run work?": the Answer explains it from the platform brief, and the turn's Exchange prompt holds no config values or health figures, and the Answer has no Claims
- [ ] As auditor on `/governance`, the Assistant panel shows `assistant_answer@v2`, the scope policy, the five limits, and the latest live eval (refusal rate, false refusals, ungrounded-Claim rate, failed turns, injection leaks) with no "run against" warning

## Assistant (Suggested Questions and replay mode)

Setup: `APP_LLM_MODE=recorded`, `APP_LLM_RECORDINGS_DIR=tests/fixtures/llm`, the default `APP_LLM_MODEL`, `APP_LLM_BASE_URL` and `APP_ASSISTANT_CONTEXT_ROWS` (the Governance context names the model and endpoint), and a fresh database seeded with `uv run python -m app.seeder`, `uv run python -m app.research_seed` and one Analysis Run as advisor. This is the seeded data the recordings were made against (`tests/fixtures/suggested_questions.py`).

- [ ] Every screen shows three Suggested Questions under the turns, and they change with the screen (Queue, Portfolio, Recommendation, Approvals, Audit, LLM Exchanges, Governance, Config, Health)
- [ ] As advisor on `/portfolios/C004`, click each Suggested Question in any order: each one replays an Answer (no "Thinking…" stall, no failure), even after a free-form Question in the same Conversation
- [ ] The replay-mode message shows: type a free-form Question (e.g. "What colour is the sky?") and Send. The turn reads "Only Suggested Questions work in replay mode." with a Retry button, and it still reads so after a reload. As auditor, its `assistant.failed` Audit Event has `reason` `replay_miss`
- [ ] Clicking a follow-up suggestion under an Answer asks it straight away about the current screen, leaving the Question box untouched; in replay mode a follow-up that isn't a Suggested Question gets the replay-mode message
- [ ] On `/audit`, a Suggested Question gets the replay-mode message: Audit Events carry wall-clock timestamps, so the Audit context never matches a recording (expected)

## Assistant (usage limits)

Setup: `APP_ASSISTANT_QUESTION_MAX_CHARS=40`, `APP_ASSISTANT_QUESTIONS_PER_CONVERSATION=3`, `APP_ASSISTANT_QUESTIONS_PER_HOUR=5` (defaults 2,000, 50 and 20). Every turn counts, failed and refused ones included.

- [ ] Paste a Question over 40 characters and Send: the drawer shows "A Question can be at most 40 characters." with no Retry, no turn is added, the Question box keeps the text, and a shorter Question still sends
- [ ] As advisor, ask three Questions, then a fourth: the drawer shows "This Conversation has reached its limit of 3 Questions. Log out and back in to start a new one." The Question box, Send, Suggested Questions, follow-ups and Retry buttons are all disabled
- [ ] Log out and back in as advisor: the limit message is gone and two more Questions send. The next one shows "You've reached the limit of 5 Questions an hour. Try again in 60 minutes." and sending stays disabled
- [ ] Log in as portfolio_manager in another browser: their Questions are not held back by the advisor's hourly count

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
