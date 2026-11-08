# 14: First ARB export, v0.1 (Draft)

**What to build:** The document owner hands the ARB a frozen v0.1 PDF stamped from a clean commit on the docs branch, with status "Draft / Under ARB Review", TBD reviewer fields, and the first version-history row (version, date, SHA, summary).

**Blocked by:** 12, 13

**Status:** resolved

- [x] Version-history row added and committed before the build
- [x] `build` run on a clean tree; cover SHA matches the commit
- [x] PDF opened and spot-checked: cover, diagrams, generated tables, page count
- [x] PDF location reported to the owner (not committed)

## Comments

The release metadata is committed on the requested current branch. The export is built from a clean local clone on `docs/architecture-document` at that commit, including the completed ticket 12 review fixes. The original repository's docs branch predates those fixes and is left untouched, as are unrelated working-tree changes.

Following ticket 03's export convention, the v0.1 row initially uses `(this export)`; the cover resolves the full commit SHA. A subsequent documentation-only commit records that SHA and the verification evidence without rebuilding the frozen PDF.

## Answer

Frozen export: `build/architecture/architecture-document-v0.1-120cfff.pdf` (ignored, not committed). Cover commit: `120cfff717621d4a527f8571348b5ef5899118d4`, dated 2026-11-08. Status: **Draft / Under ARB Review**, all reviewer fields **TBD**. Built on a clean `docs/architecture-document` branch in a local clone; clean before and after the build.

60 pages total: cover p1, document control and contents p2, Executive Summary pp3–4, body including roadmap pp5–23 (19 pages), appendices pp24–60. Cover, diagrams, generated tables and pagination visually spot-checked. SHA-256: `95cc26088417d09724784f66cadd6505f7a659d69505d06e1882a67dd0f7370f`.

Validation: 18 architecture tests passed; full suite **739 passed, 1 skipped**; Ruff lint/format, mypy, frontend lint/format/types and architecture check passed. Existing warnings: 39 frontend Fast Refresh warnings, 10 Python deprecation warnings. Standards review: **0 findings**. Spec review: **0 findings**. Full release record: [ticket 14 verification](../../../docs/architecture/reviews/14-first-arb-export-v0-1.md).
