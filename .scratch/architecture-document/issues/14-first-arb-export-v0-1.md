# 14: First ARB export, v0.1 (Draft)

**What to build:** The document owner hands the ARB a frozen v0.1 PDF stamped from a clean commit on the docs branch, with status "Draft / Under ARB Review", TBD reviewer fields, and the first version-history row (version, date, SHA, summary).

**Blocked by:** 12, 13

**Status:** claimed

- [ ] Version-history row added and committed before the build
- [ ] `build` run on a clean tree; cover SHA matches the commit
- [ ] PDF opened and spot-checked: cover, diagrams, generated tables, page count
- [ ] PDF location reported to the owner (not committed)

## Comments

The release metadata is committed on the requested current branch. The export is built from a clean local clone on `docs/architecture-document` at that commit, including the completed ticket 12 review fixes. The original repository's docs branch predates those fixes and is left untouched, as are unrelated working-tree changes.

Following ticket 03's export convention, the v0.1 row initially uses `(this export)`; the cover resolves the full commit SHA. A subsequent documentation-only commit records that SHA and the verification evidence without rebuilding the frozen PDF.
