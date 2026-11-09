# 12: ARB-reviewer pass and fixes

**What to build:** Before the board sees it, a fresh-context reviewer subagent reads the built PDF and sources as an ARB chair, model risk reviewer and InfoSec reviewer, against an arc42 completeness checklist and the spec's user stories. Findings are recorded as a comment on this ticket; each is fixed or explicitly declined with a reason.

**Blocked by:** 03, 11

**Status:** complete

- [x] Review findings appended under `## Comments` with severity
- [x] Each finding resolved or declined with reason
- [x] Body length within 15–20 pages in the PDF layout (appendices excluded)
- [x] `check` green and `build` succeeds on a clean tree

## Comments

### Fresh-context findings and dispositions

| ID | Severity | Finding | Disposition and evidence |
| --- | --- | --- | --- |
| ARB-01 | High | The baseline PDF has 38 pages: arc42 sections occupy 29 pages, or 32 including the roadmap, exceeding the 15–20-page body limit. | **Resolved.** Detailed catalogs, scenario/test mappings and registers moved into linked Appendix E. The body retains all twelve sections, C4 views and four runtime sequences. Continuous body pagination, bounded diagram heights and readable table widths replace the layout that forced each section onto a fresh page. Final clean snapshot: cover p1, document control p2, Executive Summary pp3–4, body including roadmap pp5–23 (**19 pages**), appendices pp24–60. |
| ARB-02 | High | Baseline PDF pp22–23 clip the rightmost RBAC columns, including Platform Owner permissions. | **Resolved.** Fixed-width table layout, wrapping code and explicit matrix column widths keep all eight roles inside the page. The rebuilt matrix is on p18; visual inspection confirms the rightmost column and its `config:write` and `health:read` grants. The PDF build regression checks all eight role ids in the rendered matrix. |
| ARB-03 | Medium | §1, §8.9 and QS-D1 imply universal PII prevention, but arbitrary Questions, history and Reports are not sanitized. | **Resolved.** Body and detailed scenarios limit the control to application-derived Client identity and representative fixture prompts. §8.9 explicitly states the provider-egress and Exchange-retention exposure of free-form input. Existing reply checking remains an exact stored-name/email backstop, not general PII detection. |
| ARB-04 | Medium | §8.3 says credentials can never be stored in Exchanges, contradicting parsed-content and message capture. | **Resolved.** The preserved §8.3 implementation detail and Appendix D distinguish excluded Authorization headers and redacted raw provider text from unsanitized request messages and parsed content, which can retain entered or echoed secrets. |
| ARB-05 | Low | R-02 claims every write is audited, although configuration updates write no Audit Event. | **Resolved.** The detailed R-02 register states server permission enforcement and audited business Decisions, and explicitly identifies the configuration-audit gap. |
| ARB-06 | Medium | Final Spec review observed that the lean §8.2 body retained a universal audit claim while exceptions had moved into the appendix. | **Resolved.** §8.2 and §4 explicitly name unaudited configuration changes, missing no-Trade-Line tilt anchors, scoring rollback and interrupted-recording gaps (TD-03/04/05). The detailed audit section carries the same qualification. |

No finding was declined. These are documentation and export-layout fixes; they do not implement the production controls listed in the roadmap.

### Arc42 and user-story coverage

- All twelve arc42 sections are present. System Context, Container and Component diagrams, the four critical runtime flows, ranked quality goals, concrete scenarios, non-goals, risk/debt ids and the glossary/ADR links are retained.
- User stories 1–24 and 26–27 were covered at baseline. ADR-0010 explicitly supersedes the original single-call Assistant design; the deterministic pipeline remains schema-bound and single-call.
- Stories 25 and 30 required the corrected PII and credential boundaries. Story 28 required the PDF matrix correction. Story 29 distinguishes audited endpoint denials from non-disclosing Assistant lookup results.
- Stories 31–39 remain covered by implementation pointers, generated tables, CI checks and testing documentation. Moving generated regions preserves the same `check` / `regenerate` command seam and CI drift detection.
- Stories 40–42 are covered by the two-page summary, committed Excalidraw source/image and document-control fields. Story 43's first formal v0.1 export remains ticket 14. Stories 44–45 are covered by the living-document workflow and this recorded review.
- Appendix B distinguishes historical v3 30/30 from current model-of-record v5 33/33 evidence. No additional paid live evaluation was needed for these fixes.

### Validation

The command seam in `tests/test_architecture_doc.py` remains the agreed test boundary. The PDF regression failed before the layout fixes, then passed with the 15–20-page body, at-most-two-page summary and all eight matrix roles. Detailed tests stay outside the body without losing any scenario ids or exact test references.

A clean temporary checkout validates `check` and `build` without including the user's unrelated working-tree changes. The final committed tree is rebuilt through a clean local clone so its PDF cover identifies the actual commit. Rendering stays outside normal CI, as specified. Visual review uses macOS PDFKit page renders for the cover/control block, summary, diagrams, matrix and appendix tables.

Final Standards review: **0 findings**. Final Spec review: **0 additional findings** after ARB-06 was qualified. Required automated check results are recorded in the implementation commit message.

Tracked review record: `docs/architecture/reviews/12-arb-reviewer-pass.md`.
