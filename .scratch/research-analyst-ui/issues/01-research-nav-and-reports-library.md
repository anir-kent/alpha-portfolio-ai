# 01: Research navigation and a read-only Reports library

**What to build:** The tracer bullet. A Research Analyst logs in and, instead of the empty "Select a section" shell, sees a **Research** item in the navigation and lands on the Research screen. Its **Reports** tab lists every Report in the platform as a table: title, kind, page count, uploader, upload time, extraction outcome, and the counts of Insights awaiting review, approved and rejected. Seeded Reports carry a "Human-verified seed" badge; a Report whose extraction failed shows an error pill. Roles without `report:read` never see the Research item or its route. This ticket proves the path end to end against the real API: permission-gated navigation, the regenerated typed client, the Report list, and the shared page chrome.

The **To review** tab is not built here (ticket 05); until then the Research screen opens on Reports. Clicking a row may link to a Report detail route that ticket 02 fills in.

See spec: Access; Reports library; States; Visual design.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] The typed client is regenerated from the OpenAPI schema; no hand-written request types
- [ ] A Research navigation item is shown only with the `report:read` permission, following the existing navigation-by-permission pattern; its routes are registered only for that permission
- [ ] A user whose only screen is Research (the Research Analyst) lands on it at sign-in rather than the "Select a section" placeholder; other roles' landing is unchanged
- [ ] The Reports table shows title, kind, page count, uploader, upload time, extraction outcome and the three Insight counts, all derived from the Report list response
- [ ] Seeded Reports show a "Human-verified seed" badge; failed extraction shows an error pill with text, not colour alone
- [ ] Loading shows skeleton rows; an empty list and a fetch error each have an explicit state, reusing the existing empty and error components
- [ ] Built from the existing page header, panel, pill and design tokens, so it matches the Advisor and Auditor screens
- [ ] `docs/manual-e2e-checklist.md` gains a "Research Analyst" section with this ticket's checks: Analyst lands on Research and sees the seeded Reports; an Advisor and an Auditor do not see Research
- [ ] `npm run typecheck`, `npm run lint`, `npm run format:check` and the frontend build pass
