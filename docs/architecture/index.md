# Portfolio Rebalancing: Architecture Document

An arc42 + C4 baseline of the Portfolio Rebalancing platform for Architecture Review Board, model risk / compliance and InfoSec sign-off. As-is sections describe only what the code on the baseline commit does; target state lives in the [Roadmap](13-roadmap.md). Vocabulary follows [`GLOSSARY.md`](../../GLOSSARY.md); decisions live in [`docs/adr/`](../adr/).

This document is living: it is updated in the same pull request as any architectural change. Tables between `BEGIN GENERATED` / `END GENERATED` markers are generated from the code. Do not edit them by hand. Run `uv run python -m scripts.architecture_doc regenerate`, and CI's `check` fails until you do.

## Document control

| Field | Value |
| --- | --- |
| Document | Portfolio Rebalancing: Architecture Document |
| Owner | Aniruddh Kendurkar, Principal AI/Data Architect |
| Status | Draft / Under ARB Review |
| Status values | Draft / Under ARB Review / Approved |
| Baseline | `development` after ai-portfolio-rebalancing ticket 15 |

### Reviewers

| Role | Name | Decision | Date |
| --- | --- | --- | --- |
| ARB chair | TBD | TBD | TBD |
| Model Risk | TBD | TBD | TBD |
| InfoSec | TBD | TBD | TBD |

### Version history

One row per exported PDF. The commit SHA is the one stamped on that export's cover.
`(this export)` identifies the commit containing the row, resolved to its full SHA on the cover at build time. A later documentation commit records that SHA here without rebuilding the frozen export.

| Version | Date | Commit | Status | Change |
| --- | --- | --- | --- | --- |
| 0.0 | 2026-11-07 | (unreleased) | Draft | Skeleton and document check |
| 0.1 | 2026-11-08 | (this export) | Draft / Under ARB Review | First frozen ARB baseline following the reviewer pass; includes arc42/C4 views, generated control tables and governance evidence. |

## Contents

1. [Executive Summary](00-executive-summary.md)
2. [1. Introduction and Goals](01-introduction-and-goals.md)
3. [2. Architecture Constraints](02-architecture-constraints.md)
4. [3. Context and Scope](03-context-and-scope.md)
5. [4. Solution Strategy](04-solution-strategy.md)
6. [5. Building Block View](05-building-block-view.md)
7. [6. Runtime View](06-runtime-view.md)
8. [7. Deployment View](07-deployment-view.md)
9. [8. Crosscutting Concepts](08-crosscutting-concepts.md)
10. [9. Architecture Decisions](09-architecture-decisions.md)
11. [10. Quality Requirements](10-quality-requirements.md)
12. [11. Risks and Technical Debt](11-risks-and-technical-debt.md)
13. [12. Glossary](12-glossary.md)
14. [Target / Production Roadmap](13-roadmap.md)
15. [Appendices](appendices.md)
