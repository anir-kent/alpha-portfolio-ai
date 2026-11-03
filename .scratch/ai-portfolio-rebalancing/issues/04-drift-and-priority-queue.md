# 04: Drift and priority queue

**What to build:** Asset-Class Drift with warn and breach Tolerance Bands per Risk Profile, Portfolio Drift, and the deterministic 0-100 priority score (drift 40, risk 30, opportunity 20, urgency 10; configurable) with a visible breakdown and High/Medium/Low labels. An on-demand analysis run (API action and CLI) scores all Portfolios, superseding earlier results. The Advisor sees a ranked queue with label, SLA flag and breakdown. Opportunity scores 0 until Insights exist.

**Blocked by:** 02, 03

**Status:** done

- [x] Asset-Class Drift is absolute point deviation; Portfolio Drift is half the sum of absolute deviations
- [x] Planted scenarios rank as expected; the clean Portfolio ranks Low
- [x] Score components and weights are returned with every queue row and respect config
- [x] Urgency reflects days past review-due versus SLA; queue flags SLA breaches
- [x] Analysis run is audited (Analysis run started, Priority scored)
- [x] Queue can be filtered and sorted by label, Risk Profile and review-due date; Advisor/RM role only
