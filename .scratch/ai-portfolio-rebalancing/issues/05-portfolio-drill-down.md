# 05: Portfolio drill-down

**What to build:** An Advisor opens a Portfolio and sees Holdings, an actual-vs-target allocation chart per Asset Class with drift against bands, Portfolio Drift, the Client's Risk Profile, objectives, horizon, liquidity needs and Restrictions, and look-through sector exposure including via funds. Sensitive Client fields are masked by role.

**Blocked by:** 04

**Status:** ready-for-agent

- [ ] Look-through exposure matches the reference weights on the planted scenarios
- [ ] Allocation chart and drift display agree with API values
- [ ] Relationship Manager role sees masked sensitive fields; roles without access are denied and audited
- [ ] Version/Decision history section exists (empty until later tickets)
