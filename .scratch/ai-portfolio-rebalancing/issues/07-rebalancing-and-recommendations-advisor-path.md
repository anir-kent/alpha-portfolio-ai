# 07: Rebalancing and Recommendations (Advisor-only path)

**What to build:** Band-based rule-based rebalancing that produces a Recommendation of Trade Lines (percent and currency) for a Portfolio outside tolerance, with no tilt yet. The Advisor can accept, reject with rationale, or modify Trade Lines. A modification creates a new linked version and re-runs suitability immediately. Accepting without breaches moves it to Approved ("cleared to act outside this system"); nothing executes.

**Blocked by:** 06

**Status:** done

- [x] Planted scenarios yield expected Trade Lines; clean Portfolio yields no Recommendation
- [x] Modifications create linked versions and surface new breaches to the Advisor immediately
- [x] Decisions require rationale on reject and modify and are audited with lineage
- [x] UI states clearly that Approved does not execute anything
- [x] Recommendation panel in the drill-down shows Trade Lines, suitability results and version history

## Implementation notes

- `app/rebalance.py` is pure. A Portfolio gets a Recommendation only when some Asset Class is in `breach` of its Tolerance Band. Every class then moves to target: overweight classes are sold pro rata to holding value; underweight classes are bought pro rata across the class's existing non-restricted funds (never more of a single name), or the default fund (SPY / AGG / SGOV) when there is none. Whole units rounded down; a class within 0.5 points of target is left alone. No tax-lot optimisation.
- Planted: C002 (energy) and C003 (cash drag) get Recommendations; C001, C004 have no Asset-Class Drift and C005 is clean, so none.
- `app/recommendations.py` owns drafting and Decisions. Each version stores its Trade Lines (percent and currency), turnover, and suitability evaluated on the **post-trade** Portfolio (same `suitability.evaluate` call).
- Status: `pending_advisor` -> `approved` | `pending_compliance` (accepted with a breach; Compliance acts in 08) | `rejected` | `superseded`. Modify makes a linked version (`parent_id`, `version`), supersedes the old one, re-runs suitability and returns `new_breaches`. Reject and modify need a rationale (422). A new analysis run supersedes open Recommendations.
- Audit: `recommendation_drafted` -> `suitability_evaluated` (post-trade) -> `decision_recorded` -> `recommendation_modified` -> `suitability_evaluated`, each chained by parents, tagged with `recommendation_id`. New event type `recommendation_superseded`.
- API: `GET /api/recommendations/{id}`, `POST /api/recommendations/{id}/decision`; drill-down carries `recommendation` and `history` (versions, decisions). UI: `RecommendationPanel` states that Approved executes nothing.
- Carry-forward for 08: accepting currently skips the high-impact (turnover / single Trade Line) check, so a high-impact accept with no breach goes straight to `approved`; 08 must route it to the Investment Committee.
