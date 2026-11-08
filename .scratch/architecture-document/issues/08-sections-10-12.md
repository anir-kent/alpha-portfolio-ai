# 08: §10 Quality scenarios, §11 Risks & technical debt, §12 Glossary

**What to build:** A reviewer can judge the design against measurable scenarios and see every known gap. §10: quality tree for the five ranked goals with at least one concrete scenario each (e.g. tampering with an Audit Event is detected by verify; an ungrounded Claim never reaches the memo). §11: risk register with severity and mitigation for: no SSO/MFA, no CSRF token, `Secure` cookie off by default, single process, SQLite, in-process Run Step progress, no structured logging/metrics/tracing, no frontend test runner, synthetic data, LLM provider dependency. §12 links to `GLOSSARY.md` without copying it.

**Blocked by:** 01, 04

**Status:** resolved

- [x] Every quality goal from §1 has ≥1 scenario with stimulus, response and measure
- [x] Every agreed gap appears in §11 with severity, impact and a mitigation pointer (Roadmap anchor added in ticket 09)
- [x] §12 links glossary; `check` green

## Comments

**2026-11-08, implementation (Claude).**
- **§10:** a quality tree (Mermaid) and 18 scenarios across the five ranked goals. Each scenario has a stimulus, response and measure, and names the tests in `tests/` that assert it. Every cited test was checked to exist. §10.3 states the non-goals and points to R-04 to R-06.
- **§11:** a severity scale (rated for production), then risks R-01 to R-09 and technical debt TD-01 to TD-07. Every entry has an explicit anchor (`#r-01`, `#td-01`, …) so ticket 09 can link Roadmap items back.
  - Agreed gaps: R-01 to R-08, TD-01 and TD-02.
  - The two gaps ticket 06 handed over: TD-03 (the unanchored Research Tilt Exchange) and TD-04 (Tilt Exchanges rolled back on a scoring failure).
  - Added beyond the agreed list, because the code shows them: R-09 (the audit chain has no external anchor, so a full rehash of the tail verifies), TD-05 (ADR-0009), TD-06 (the recording key omits the model) and TD-07 (hand-written migrations).
- **§12:** links each `GLOSSARY.md` category heading and its term names. No definitions are copied.
- **For ticket 09:** every Mitigation cell links `13-roadmap.md#roadmap-items`. Replace each one with the anchor of its Roadmap item.
- **Review:** Standards found no hard violations; I applied the glossary wording fixes. Spec found two factual errors, now fixed: TD-01's logging claim, and R-01 (users are created at startup, not by the seeder). Repeated config values in §11 were kept on purpose, because the reviewer needs them inline.
- **Verified:** `check` OK. `tests/test_architecture_doc.py` 18 passed. The full pytest run (635 passed, 1 skipped) was before the review edits, which touched only the Markdown.
