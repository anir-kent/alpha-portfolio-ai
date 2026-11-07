# 08: §10 Quality scenarios, §11 Risks & technical debt, §12 Glossary

**What to build:** A reviewer can judge the design against measurable scenarios and see every known gap. §10: quality tree for the five ranked goals with at least one concrete scenario each (e.g. tampering with an Audit Event is detected by verify; an ungrounded Claim never reaches the memo). §11: risk register with severity and mitigation for: no SSO/MFA, no CSRF token, `Secure` cookie off by default, single process, SQLite, in-process Run Step progress, no structured logging/metrics/tracing, no frontend test runner, synthetic data, LLM provider dependency. §12 links to `GLOSSARY.md` without copying it.

**Blocked by:** 01, 04

**Status:** ready-for-agent

- [ ] Every quality goal from §1 has ≥1 scenario with stimulus, response and measure
- [ ] Every agreed gap appears in §11 with severity, impact and a mitigation pointer (Roadmap anchor added in ticket 09)
- [ ] §12 links glossary; `check` green
