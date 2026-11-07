# 04: Approve or reject an Insight

**What to build:** On Report detail, an Insight awaiting review gets **Approve** and **Reject** actions at the top of the detail pane. Approve is one explicit action with an optional note (collapsed by default). Reject opens a dialog with a required note; submit stays disabled until the note has content. Both actions disable while saving. After the server confirms, the Insight becomes read-only with its outcome, reviewer, time and note, the counts move at once, and the selection advances to the next Insight awaiting review in this Report. If another Analyst reviewed it first (409), a non-blocking notice says so, the data refreshes and the selection advances. Any other failure shows an inline error and leaves the selection in place. The UI makes clear that an Insight Review is final.

See spec: Insight Review interaction; "To review" is client-side aggregation (cache update then refetch).

**Blocked by:** 02 (verify with Insights awaiting review from ticket 03's upload, or from `POST /api/reports` if 03 is not done yet)

**Status:** ready-for-agent

- [ ] Approve and Reject appear only for an Insight awaiting review and only with the `insight:approve` permission
- [ ] Approve sends the Insight Review with the optional note; Reject requires a non-empty note in a dialog
- [ ] The reject dialog focuses the note on open, traps focus, closes on Escape without submitting, and returns focus to Reject
- [ ] Both actions are disabled while saving, so an Insight Review cannot be submitted twice
- [ ] On success the cached Report list is updated immediately (counts in the library and detail move at once), then refetched
- [ ] Selection advances to the next Insight awaiting review in this Report; when none remain the detail says the Report is fully reviewed
- [ ] A 409 shows a non-blocking "Already reviewed by someone else" notice, refreshes, and advances
- [ ] Other failures show an inline error in the detail pane and keep the selection
- [ ] Copy near the actions states that an Insight Review is final; UI text never says "decide" or "Decision"
- [ ] The Research Analyst checklist section gains: approve with and without a note; reject requires a note; reject a mis-tagged Insight with a note saying what was wrong; the 409 race using two browser sessions on the same Insight
- [ ] Typecheck, lint, format check and build pass
