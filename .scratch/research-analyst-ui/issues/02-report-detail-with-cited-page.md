# 02: Report detail with every Insight beside its cited page

**What to build:** From the Reports library, a Research Analyst opens a Report and sees its metadata and all its Insights in the review layout. Left: the Insight list, in page order, each row showing subject, direction, confidence and status, with a status filter (awaiting review / approved / rejected / all). Right: the selected Insight's subject with its kind (sector or Asset Class), direction and confidence as tone pills, its page number, and the full text of the cited Report page with the cited passage highlighted and scrolled into view. When the passage is not found verbatim, the page shows unhighlighted with the warning "Cited passage not found verbatim on page N". A reviewed Insight shows a read-only record of outcome, reviewer, time and note, plus a human-verified marker for seeded ones. A page picker lets the Analyst read any page of the Report. The selected Insight is reflected in the URL, so a reload or a shared link returns to it.

This ticket is read-only: no approve or reject yet (ticket 04). It is fully verifiable on the seeded Reports, whose Insights are all approved.

See spec: Review layout; Passage matching; Reports library (detail); States.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Report detail header shows title, kind, page count, uploader, upload time and the human-verified seed badge where it applies
- [ ] A Report whose extraction failed shows the stored extraction error; a Report that succeeded with no Insights shows the neutral "No Insights were extracted from this Report" state with its page count, without error styling
- [ ] The Insight list is in page order (then ID) and filters by status; the filter state survives a reload
- [ ] Selecting an Insight fetches its cited page (cached per page) and highlights the passage, using whitespace-insensitive, case-sensitive matching, and scrolls it into view
- [ ] When no match is found the page is shown unhighlighted with the not-found warning naming the page
- [ ] Reviewed Insights show outcome, reviewer, time and note read-only; UI text says "review", "approve", "reject", never "decide" or "Decision"
- [ ] The page picker shows any page of the Report
- [ ] The selected Insight is in the URL; reload and deep link restore it; an unknown Insight or Report gets a clear not-found state
- [ ] At narrow widths the two panes stack (list above detail); at 1280px and wider they sit side by side
- [ ] Loading, empty and error states for the Report, its Insights and the page text
- [ ] The Research Analyst checklist section gains: open a seeded Report, see the highlighted passage, switch page, filter by status, reload on a selected Insight
- [ ] Typecheck, lint, format check and build pass
