# 07: Analyst walkthrough, downstream Advisor check and polish

**What to build:** The Research Analyst journey becomes part of the demo and the manual end-to-end evidence. The guide's "API-only roles" act for `research_analyst` is replaced by a Research Analyst act driven through the UI: land on To review, upload the demo house view, review its Insights (approve some, reject one with a note), then sign in as an Advisor and confirm on a relevant Portfolio drill-down that the newly approved Insight appears and the rejected one does not. A final polish pass checks the whole Research screen against the spec's cross-cutting UX: loading, empty and error states on every view, stacking below the breakpoint, contrast, text-plus-colour status, and consistency with the Advisor and Auditor screens.

See spec: Testing Decisions (Seam 3); Further Notes (Done criteria).

**Blocked by:** 03, 06

**Status:** resolved

- [x] `docs/manual-e2e-guide.md` replaces the `research_analyst` part of the API-only roles act with a Research Analyst act through the UI; `portfolio_manager` and `platform_owner` stay as they are
- [x] The Research Analyst section of `docs/manual-e2e-checklist.md` is complete and ordered as one run, ending with the downstream Advisor check
- [ ] Walking the checklist end to end passes, including: an approved Insight appearing on the Advisor's Portfolio drill-down and a rejected or still-awaiting-review Insight never appearing there
- [x] Every Research view has distinct loading, empty and error states; no view shows a blank pane without explanation
- [x] At 1280px and wider the layout is side by side; below the breakpoint the review panes stack and remain usable
- [x] Status is conveyed by text as well as colour, and text and pills meet WCAG AA contrast
- [x] UI text uses `GLOSSARY.md` terms (Report, Insight, Insight Review, awaiting review) and never "decide", "Decision", "signal" or "finding"
- [x] README mentions the Research Analyst screen where it lists the working UI roles
- [x] Typecheck, lint, format check and the frontend build pass; the backend suite still passes unchanged

**Note:** the end-to-end walk of the checklist is left for the manual E2E pass after all tickets. The data path behind the downstream check was exercised against a scratch database: approved Information Technology appears for the Advisor; rejected Utilities and still-awaiting-review equity do not. The Advisor drill-down had no deterministic Insight list (only LLM-dependent tilt rows and citations), so an "Approved research" panel reading the existing approved-only `GET /api/insights` was added to the Portfolio page; no backend change.
