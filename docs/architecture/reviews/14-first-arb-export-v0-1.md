# Ticket 14: First ARB export, v0.1

## Frozen baseline

| Field | Value |
| --- | --- |
| Version | 0.1 |
| Date | 2026-11-08 |
| Status | Draft / Under ARB Review |
| Source commit | `120cfff717621d4a527f8571348b5ef5899118d4` |
| Owner | Aniruddh Kendurkar, Principal AI/Data Architect |
| Reviewers | ARB chair, Model Risk and InfoSec: name, decision and date all TBD |
| Local artifact | `build/architecture/architecture-document-v0.1-120cfff.pdf` (not committed) |
| Size | 3,463,719 bytes |
| SHA-256 | `95cc26088417d09724784f66cadd6505f7a659d69505d06e1882a67dd0f7370f` |

The history row was committed before the build, initially with `(this export)` as specified by ticket 03. This later documentation record fills its source SHA without rebuilding or modifying the frozen PDF. The cover contains the full source commit, version, date, owner and status. The exported history row retains `(this export)` and resolves against that cover.

## Build provenance

Release metadata was committed on `feature/pydantic-ai-agentic-assistant`, as requested by the implement workflow. A separate local clone at `/private/tmp/alpha-arb-v0-1-export` was fast-forwarded to the source commit on its `docs/architecture-document` branch. The original repository's older docs branch and unrelated working files were preserved.

The clone had empty `git status --porcelain=v1 --untracked-files=all` output before and after the build. Its origin was the project's GitHub URL so repository links are pinned to the source SHA. With the project's uv virtual environment activated, the build ran from the clone:

```bash
python -m scripts.architecture_doc build --out /Users/aniruddh/git/alpha-portfolio-ai/build/architecture
```

The builder's clean-tree gate passed. The resulting PDF is git-ignored in the owner's workspace and is not included in any commit.

## PDF verification

PDF text and outline checks confirmed 60 pages, the full cover SHA/date/status/version, all nine TBD reviewer cells and all eight role columns in the generated RBAC matrix. Page allocation:

| Content | Pages |
| --- | --- |
| Cover | 1 |
| Document control, reviewers, version history and complete contents | 2 |
| Executive Summary | 3–4 |
| Twelve arc42 sections and production roadmap | 5–23 (19 pages) |
| Appendices | 24–60 |

macOS PDFKit opened the final PDF and rendered pages for visual inspection. Spot checks covered cover/control (pp1–2), summary and Excalidraw image (pp3–4), container/components (pp9–10), four runtime sequences (pp12–15), generated RBAC matrix (p18), model-of-record evidence and framework mapping (pp27–28), generated settings/limits and quality tables (p40), runtime detail (p50) and final roadmap page (p60). The inspected tables stay within page edges, diagrams render, and page numbering is consistent. Dense vector diagrams remain zoomable.

An initial candidate at `4fdb6d8` had 61 pages because the longer release-history wording pushed two contents entries to an extra front-matter page. Shortening that wording in the source commit restored the complete contents to p2 and the 60-page layout. Only the `120cfff` artifact is the frozen v0.1 export.

## Validation and review

- Architecture command tests: **18 passed**, including rendered cover, vector diagrams, body/summary length and all RBAC columns. Tests now own fixture release metadata rather than requiring the real document to remain version 0.0 / Draft.
- Full Python suite: **739 passed, 1 skipped**, with 10 existing deprecation warnings.
- Ruff lint and format check, mypy (112 files), frontend lint/format/typecheck: passed. Frontend lint retains 39 existing Fast Refresh warnings, zero errors.
- Architecture `check` with Mermaid: passed. The final build rendered diagrams again and checked sections, links and generated regions.
- Standards review: **0 findings**.
- Spec review: **0 findings**.

The owner was given the artifact location. Reviewers remain TBD; this export records no board approval.
