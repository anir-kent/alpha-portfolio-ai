# 07: Rebalancing and Recommendations (Advisor-only path)

**What to build:** Band-based rule-based rebalancing that produces a Recommendation of Trade Lines (percent and currency) for a Portfolio outside tolerance, with no tilt yet. The Advisor can accept, reject with rationale, or modify Trade Lines. A modification creates a new linked version and re-runs suitability immediately. Accepting without breaches moves it to Approved ("cleared to act outside this system"); nothing executes.

**Blocked by:** 06

**Status:** ready-for-agent

- [ ] Planted scenarios yield expected Trade Lines; clean Portfolio yields no Recommendation
- [ ] Modifications create linked versions and surface new breaches to the Advisor immediately
- [ ] Decisions require rationale on reject and modify and are audited with lineage
- [ ] UI states clearly that Approved does not execute anything
- [ ] Recommendation panel in the drill-down shows Trade Lines, suitability results and version history
