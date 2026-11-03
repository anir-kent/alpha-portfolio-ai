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

## Implementation notes (carry-forward)

Implemented in `34277b8`. Choices and open items for later tickets:

- **Score normalisation** (spec silent): drift = Portfolio Drift, full at 10 pp (`DRIFT_FULL_PP` in `app/priority.py`); risk = worst Asset-Class Drift / Risk Profile breach threshold; urgency = days past review-due / `sla_days`. SLA breached when days past due >= `sla_days`. Days measured at the market snapshot date.
- **Planted scenarios:** ranking is asserted only for C002, C003 (High) and C005 (Low). C001 (heavy tech) and C004 (restricted instrument) have no Asset-Class Drift, so they rank low; they should surface via ticket 06.
- **Portfolio Manager** lost `queue:read` (ticket says Advisor/RM only) and now has no drift endpoint. Spec story 51 wants PMs reading Portfolios and drift: see ticket 05.
- **Not in config:** `DRIFT_FULL_PP` (10 pp) and the High/Medium cut-offs (70/40) are code constants. Revisit in ticket 12 if they should be configurable.
- **Cosmetic, unfixed:** `sort=risk_profile` is alphabetical, not by risk level; `run_analysis` is long; `Label` literal is defined twice; component names repeated across `priority.py`, router and `QueuePage.tsx`.
- Extras beyond the ticket: `sla_breached` filter, `asset_class_drift` and `total_value` in queue rows, run history kept (latest completed run is current), thin `QueuePage`.
