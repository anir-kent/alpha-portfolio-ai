# 08: Tiered approvals

**What to build:** The full lifecycle: Pending Compliance only when any rule is in breach (Compliance approves an exception with rationale or blocks); Pending Investment Committee only when high-impact (turnover 15% or more, or any single Trade Line 10% or more, configurable). One shared pending-approvals panel serves Compliance and the Investment Committee. A new analysis run or modification marks earlier Recommendations Superseded.

**Blocked by:** 07

**Status:** ready-for-agent

- [ ] No Recommendation can reach Approved without a human Decision at every required step (invariant test via the API, including attempts to skip steps)
- [ ] Compliance cannot act before the Advisor has decided
- [ ] Exception approve and block, and Investment Committee decisions, require rationale and are audited
- [ ] Thresholds read from config
- [ ] Compliance view shows rule ID, limit, actual and affected Trade Line, plus Client Restrictions
- [ ] Superseded Recommendations cannot be decided
