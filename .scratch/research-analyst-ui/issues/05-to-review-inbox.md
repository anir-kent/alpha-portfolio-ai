# 05: The To review inbox as the Analyst's landing page

**What to build:** The Research screen gains a **To review** tab, which becomes the Research Analyst's landing page. It lists every Insight awaiting review across all Reports, grouped by Report, newest Report first, Insights within a group in page order. Each group header shows the Report's title, uploader, upload time and how many Insights remain to review. The tab carries a badge with the total awaiting review. Selecting an Insight uses the same review detail and actions as Report detail (tickets 02 and 04), and after an Insight Review the selection advances to the next Insight awaiting review in inbox order, across Report boundaries. When nothing is awaiting review the tab shows an "All caught up" state, which is the normal state on a freshly seeded database.

See spec: "To review" is client-side aggregation; Review layout; Insight Review interaction.

**Blocked by:** 04

**Status:** resolved

- [x] The inbox is built from the Report list; no new API call or backend change
- [x] Groups are ordered by Report upload time, newest first; Insights by page then ID
- [x] Group headers show title, uploader, upload time and remaining count; the tab badge shows the total; both agree with the library counts at all times
- [x] The Research Analyst lands on To review at sign-in and when opening Research
- [x] Review detail and Approve/Reject behave exactly as on Report detail, including the 409 notice and inline errors
- [x] After an Insight Review the selection advances in inbox order; a group disappears when its last Insight is reviewed
- [x] The selected Insight is in the URL, so reload and deep links restore it
- [x] "All caught up" shows when nothing awaits review, and is visibly different from loading and error states
- [x] The Research Analyst checklist section gains: fresh database shows All caught up; after uploading the demo house view its Insights appear grouped in page order; reviewing the last Insight of a group removes the group and the badge reaches zero
- [x] Typecheck, lint, format check and build pass
