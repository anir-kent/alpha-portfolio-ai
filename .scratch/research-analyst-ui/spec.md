Status: ready-for-agent

# Research Analyst UI: upload Reports and review Insights

Source requirements: `specs/AI_Portfolio_Rebalancing_Use_Case_Requirements_and_Scope.md` (Research Analyst: "upload/validate research report → review extracted themes → approve insight taxonomy"). Extends `.scratch/ai-portfolio-rebalancing/spec.md` stories 47–50, whose API was delivered by its ticket 09. Vocabulary follows `GLOSSARY.md`, in particular **Report**, **Insight** and **Insight Review**. Respects ADR-0001 (the engine owns numbers) and ADR-0002 (append-only audit chain). No backend change.

## Problem Statement

A Research Analyst is the human check between the LLM and the Portfolios: no Insight can inform a Research Tilt until an Analyst approves it. Today that check is only reachable through the API. An Analyst who logs in sees an empty shell with no navigation, because none of the screens are gated on their permissions. To upload a Report they must craft a multipart request; to review an Insight they must read its cited passage out of a JSON payload, then post a decision by ID, with no sight of the page the passage came from. That makes the review slow, error-prone, and easy to rubber-stamp, which defeats the point of keeping a human in the loop on AI-extracted research.

## Solution

A single **Research** screen, shown only to roles that can read Reports, with two tabs:

- **To review** (the Analyst's landing page): every Insight awaiting review across all Reports, grouped by Report. Selecting an Insight shows its subject, direction and confidence beside the full text of the cited Report page, with the cited passage highlighted and scrolled into view. The Analyst approves with one click or rejects with a required note, and the screen advances to the next Insight awaiting review. The whole flow is keyboard-operable.
- **Reports**: the library of every Report with its extraction outcome and Insight counts by status. Opening a Report shows all its Insights in the same review layout, with reviewed ones read-only alongside who reviewed them, when, and why.

An **Upload Report** action in the page header opens a dialog that accepts a PDF or text file, shows a clear in-progress state while Insights are extracted, and lands the Analyst on the new Report ready to review.

## User Stories

### Getting there
1. As a Research Analyst, I want a Research item in the navigation, so that I can reach my work without knowing a URL.
2. As a Research Analyst, I want to land on the To review tab when I log in, so that the first thing I see is the work waiting for me.
3. As a Research Analyst, I want the To review tab to show a count of Insights awaiting review, so that I know the size of the backlog at a glance.
4. As a user whose role cannot read Reports, I want the Research item hidden, so that I am not shown screens I cannot use.
5. As an Auditor, I want the server to keep denying and auditing Report and Insight actions by roles without the permission, so that hiding the screen is not the only control.

### Reviewing Insights
6. As a Research Analyst, I want Insights awaiting review grouped by Report, newest Report first, so that I review one document at a time.
7. As a Research Analyst, I want each Report group to show its title, uploader, upload time and how many Insights remain to review, so that I know whose research it is and how much is left.
8. As a Research Analyst, I want Insights within a Report listed in page order, so that I move through the document in the order it was written.
9. As a Research Analyst, I want each Insight in the list to show its subject, direction and confidence, so that I can scan the extraction before opening it.
10. As a Research Analyst, I want the selected Insight's subject (sector or Asset Class), direction and confidence shown prominently, so that I know exactly what claim I am approving.
11. As a Research Analyst, I want the full text of the cited Report page shown beside the Insight, so that I judge the claim in its surrounding context and not from an excerpt alone.
12. As a Research Analyst, I want the cited passage highlighted on that page and scrolled into view, so that I can find the evidence immediately.
13. As a Research Analyst, I want a clear warning when the cited passage cannot be found verbatim on the page, so that I know the citation itself is questionable.
14. As a Research Analyst, I want to still approve or reject when the passage is not found, so that I remain the judge and can record the citation problem in a reject note.
15. As a Research Analyst, I want the page number of the citation shown, so that I can cross-check against the original document.
16. As a Research Analyst, I want to approve an Insight with one explicit action, so that reviewing a batch stays quick.
17. As a Research Analyst, I want to add an optional note when approving, so that I can record context for later readers.
18. As a Research Analyst, I want rejecting to require a note in a small dialog, so that every rejection carries a reason on record.
19. As a Research Analyst, I want to reject a mis-tagged Insight (wrong sector, direction or confidence) with a note saying what was wrong, so that the taxonomy stays correct even though I cannot edit the Insight.
20. As a Research Analyst, I want the UI to make clear that an Insight Review is final, so that I do not approve casually.
21. As a Research Analyst, I want the screen to advance to the next Insight awaiting review after I review one, so that I keep my flow.
22. As a Research Analyst, I want a clear "all caught up" state when nothing is awaiting review, so that I know the backlog is empty rather than failing to load.
23. As a Research Analyst, I want my Insight Review reflected in the counts immediately, so that the screen never shows stale progress.
24. As a Research Analyst, I want the action buttons disabled while my Insight Review is being saved, so that I cannot submit it twice.
25. As a Research Analyst, I want a clear inline error if saving my Insight Review fails, so that I know it did not take effect and can retry.
26. As a Research Analyst, I want a non-blocking notice when another Analyst reviewed the same Insight first, so that I understand why my action did not apply, and the screen refreshes and moves on.
27. As a Research Analyst, I want to approve Insights from a Report I uploaded myself, so that a single Analyst can complete the review.

### Keyboard
28. As a Research Analyst, I want to move between Insights with `j`/`k` and the arrow keys, so that I can review without the mouse.
29. As a Research Analyst, I want `a` to approve and `r` to open the reject dialog, so that the common actions are one keystroke.
30. As a Research Analyst, I want the shortcuts shown next to their buttons, so that I can discover them.
31. As a Research Analyst, I want shortcuts disabled while I am typing in a text field, so that writing a note never triggers an action.
32. As a Research Analyst, I want focus managed in the reject dialog (focused on open, trapped while open, returned on close, Escape cancels), so that the dialog is usable by keyboard and screen reader.
33. As a Research Analyst using assistive technology, I want every action available as a labelled button and status conveyed in text, not colour alone, so that the screen is accessible.

### Reports library and detail
34. As a Research Analyst, I want a Reports tab listing every Report with title, kind, page count, uploader, upload time and extraction outcome, so that I see all research in the platform.
35. As a Research Analyst, I want each Report row to show its Insight counts awaiting review, approved and rejected, so that I see the state of its review.
36. As a Research Analyst, I want seeded Reports marked as human-verified seeds, so that I can tell them from machine-extracted research.
37. As a Research Analyst, I want to open a Report and see all its Insights in the review layout, so that I can work on or inspect one document.
38. As a Research Analyst, I want to filter a Report's Insights by status, so that I can focus on what is awaiting review or audit what was approved.
39. As a Research Analyst, I want reviewed Insights shown read-only with reviewer, time, outcome and note, so that I have a record of past Insight Reviews without audit access.
40. As a Research Analyst, I want a Report whose extraction failed to show the stored error, so that I understand why it has no Insights.
41. As a Research Analyst, I want a Report where extraction succeeded but kept no Insights to say so neutrally, so that I do not mistake a valid empty result for a failure.
42. As a Research Analyst, I want to read any page of a Report, so that I can check context beyond the cited page.

### Uploading
43. As a Research Analyst, I want an Upload Report action in the page header, so that adding research is always one click away.
44. As a Research Analyst, I want to pick or drag and drop a PDF or text file, so that uploading fits how I already work with files.
45. As a Research Analyst, I want files of the wrong type or over 20 MB rejected before upload with a clear message, so that I do not wait for a failure the browser can predict.
46. As a Research Analyst, I want an optional title that defaults to the file name, so that Reports are recognisable in the library.
47. As a Research Analyst, I want a clear in-progress state ("Extracting Insights…") with the form disabled while the upload runs, so that I know the system is working and do not resubmit.
48. As a Research Analyst, I want to land on the new Report after a successful upload, so that I can start reviewing its Insights straight away.
49. As a Research Analyst, I want server errors (too large, unreadable file) shown inline in the dialog, so that I can correct and retry without losing context.
50. As a Research Analyst, I want a failed extraction to show its error with an "Upload again" action, so that recovering is obvious.

### Downstream effect
51. As an Advisor, I want an Insight the Analyst just approved to appear among the Insights on a relevant Portfolio drill-down, so that the Analyst's review demonstrably reaches my work.
52. As an Advisor, I want Insights the Analyst rejected or has not yet reviewed never to appear on my screens, so that unvetted research never influences my Recommendations.

### Cross-cutting UX
53. As a Research Analyst, I want loading, empty and error states on every view, so that I never face a blank screen without explanation.
54. As a Research Analyst, I want the screen to work at desktop widths of 1280px and above, with the review split stacking at narrower widths, so that it is usable on any desk monitor.
55. As a Research Analyst, I want the Research screen to look and behave like the rest of the platform, so that it feels like one product.

## Implementation Decisions

**No backend change.** Every capability rests on the existing research API contract: upload a Report (multipart file plus optional title; 201 with the Report and its Insights, 413 too large, 422 unreadable), list Reports (each with all its Insights in every status), get a Report, get a Report page's text, and record an Insight Review (approve or reject with an optional note; 409 if the Insight is no longer awaiting review). The approved-only Insight listing is the Advisor-side retrieval and is not used by these screens. The typed client is regenerated from the OpenAPI schema, not hand-written.

**Access.** The Research navigation item and its routes are gated on the `report:read` permission from the session, following the existing navigation-by-permission pattern. Upload is shown only with `report:upload`; review actions only with `insight:approve`. Today only the Research Analyst role holds these. The server remains the only enforcement point. When the Analyst signs in and has no other landing screen, the default route resolves to the To review tab.

**"To review" is client-side aggregation.** The inbox is built from the Report list by taking each Report's Insights awaiting review. Groups are ordered by Report upload time, newest first; Insights inside a group by page then ID. Counts in the tab badge, group headers and library rows come from the same data, so they always agree. After the server confirms an Insight Review, the Insight is updated in the cached Report list immediately (so counts move at once) and the list is then refetched (TanStack Query).

**Review layout (master–detail).** Left: the Insight list (grouped on To review, flat with a status filter on Report detail). Right: the selected Insight: subject with its kind (sector or Asset Class), direction and confidence as tone pills reusing the existing pill and tone vocabulary; the page number; the full cited page text fetched per page and cached; the cited passage highlighted and scrolled into view. Approve and Reject sit at the top of the detail pane with their keyboard hints. For a reviewed Insight the actions are replaced by a read-only record of outcome, reviewer, time and note, and a human-verified marker for seeded ones. Below the breakpoint the two panes stack. The list's selection is reflected in the URL so a reload or link returns to the same Insight.

**Passage matching.** The highlight finds the cited passage in the page text using whitespace-insensitive, case-sensitive matching. If no match is found, the page is shown unhighlighted with a warning that the passage was not found verbatim on page N, and both actions stay enabled.

**Insight Review interaction.** Approve is a single action with an optional note field (collapsed by default). Reject opens a modal dialog with a required note; submit is disabled until the note has content. Both actions disable while saving. On success the selection advances to the next Insight awaiting review in display order; when none remain, an "all caught up" state shows. On 409 a non-blocking notice says the Insight was already reviewed by someone else, the data refetches, and the selection advances. Any other failure shows an inline error in the detail pane and leaves the selection in place. UI text uses "review", "approve" and "reject" and never "decide" or "Decision" (reserved for Recommendations).

**Keyboard model.** `j`/↓ next Insight, `k`/↑ previous, `a` approve, `r` open reject dialog, Escape closes the dialog. Shortcuts are ignored while focus is in a text input, textarea or the dialog, and when the selected Insight is not awaiting review. The reject dialog focuses its note on open, traps focus, and returns focus to the Reject button on close.

**Reports library.** A table with title, kind, page count, uploader, upload time, extraction outcome and the three Insight counts; seeded Reports carry a "Human-verified seed" badge; failed extraction is shown as an error pill. Rows open Report detail. Report detail has a header with the Report's metadata, the stored extraction error when it failed, a neutral "No Insights were extracted from this Report" state when it succeeded with none, and a page picker to read any page.

**Upload dialog.** Opened from the page header. Accepts a picked or dropped file; the browser rejects anything other than PDF or plain text and anything over 20 MB, matching the server limit, before sending. Optional title defaults to the file name. While the request runs, the dialog shows "Extracting Insights from your Report…", disables its controls and cannot be dismissed by accident. On success it closes and navigates to the new Report's detail. A 413 or 422 is shown inline in the dialog. A Report that comes back with failed extraction lands on its detail showing the error and an "Upload again" action that reopens the dialog.

**States.** Every view has explicit loading (skeleton rows, not spinners over blank space), empty and error states, reusing the existing empty and error components.

**Visual design.** Built from the existing design tokens, page header, panel, pill, empty-state and error components so the screen matches the Advisor and Auditor views. Status is always conveyed by text plus colour; contrast meets WCAG AA. Visual details are settled while implementing using the `frontend-design` skill, within the existing system rather than a new one.

**Assistant drawer.** Not wired here. The Research screens become a Screen Context under `sme-assistant` ticket 07.

## Testing Decisions

- **Seam 1: the HTTP API (existing, primary).** No new backend tests are expected, because the backend does not change and the research API's behaviour (Insights awaiting review on upload, Insight Review transitions, approved-only retrieval for tilt use, 409 on a repeat review, denial and auditing for other roles) is already covered by the suite from `ai-portfolio-rebalancing` ticket 09. If implementation finds a contract gap the UI depends on, the test is added at this seam, asserting HTTP responses and Audit Events only.
- **Seam 2: the generated OpenAPI client as a type contract.** Each ticket regenerates the client and must pass `npm run typecheck` and `npm run lint`, so any drift between UI and API fails the build.
- **Seam 3: the manual end-to-end checklist.** A new Research Analyst section in `docs/manual-e2e-checklist.md` and `docs/manual-e2e-guide.md` covers: Analyst landing and navigation; another role not seeing Research; upload of a seeded-style PDF through to its Report; reviewing with mouse and with keyboard; reject requiring a note; the passage-not-found warning; the 409 race (two browser sessions); a failed upload and an oversized file; a Report with no Insights; and finally the newly approved Insight appearing on an Advisor's Portfolio drill-down while a rejected one does not.
- No frontend test runner is introduced, consistent with `CODING_STANDARDS.md`. Passage matching and the keyboard model are small enough to verify through the checklist.
- Prior art: the existing Auditor and Advisor screens for page structure and data fetching; the existing manual checklist sections for the verification format.

## Out of Scope

- Editing or correcting an Insight before approval (changes what an Insight is; needs its own design and an ADR touching the audit chain).
- A "where is this Insight used" view across Portfolios and Research Tilts (needs RBAC and backend change).
- Re-opening or undoing an Insight Review.
- Four-eyes review (a second Analyst approving the uploader's Insights).
- Background or progress-streamed extraction, and retrying a failed extraction in place.
- The Assistant drawer on Research screens (`sme-assistant` ticket 07).
- Mobile layouts; widths below the stacking breakpoint beyond a usable stacked view.
- Bulk approve or reject.
- Any backend, schema or RBAC change.

## Further Notes

- Work on a `feature/research-analyst-ui` branch cut from `development`, separate from the conversational-assistant branch, so the two features merge independently.
- **Done criteria**: the Research Analyst checklist section passes end to end, including the downstream Advisor check; typecheck, lint, format check and the frontend build are green.
