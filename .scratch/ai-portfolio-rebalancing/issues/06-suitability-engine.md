# 06: Suitability engine

**What to build:** The seven deterministic Suitability Rules: max equity share by Risk Profile, single-position limit, sector concentration with look-through, minimum cash reserve, Client Restrictions, horizon check, and a taxable-gain warning. Each returns pass, warning or breach with rule ID and the numbers behind it. Results are shown on the drill-down and feed the priority risk component.

**Blocked by:** 05

**Status:** done

**Carry-forward from 04:** planted scenarios C001 (heavy tech) and C004 (restricted instrument) have no Asset-Class Drift and rank low in the queue; once suitability feeds the risk component, add ranking assertions for them. The risk component is currently worst Asset-Class Drift / breach threshold (`app/priority.py`).

- [x] Each rule has tests with exact numbers on the planted scenarios
- [x] Restricted-instrument scenario returns a breach naming the rule and Instrument
- [x] Clean Portfolio passes all rules
- [x] Suitability evaluation is audited with its results
- [x] Priority risk component uses these results
- [x] Full tax-lot optimisation is not implemented

## Implementation notes

- `app/suitability.py` is pure: it takes Holdings (the `portfolio_view.holdings` shape), a `ClientContext` and `SuitabilityLimits`, so ticket 07 can evaluate a proposed post-trade Portfolio with the same call. Rules SR-01..SR-07 return `RuleResult` with `Finding`s (subject, actual %, limit %, status).
- Limits live in `Config.suitability` (editable via `PATCH /api/config`, merged per field and per Risk Profile). Defaults: equity cap 30/55/80/95 by profile, 10% single name (funds exempt), 30% sector with look-through (Cash / Fixed Income buckets excluded), cash floor 5/3/2/1, short horizon under 5 years caps equity at 40%, taxable-gain warning at 15% of Portfolio value. SR-01..03 warn from 90% of the limit.
- SR-04: breach below the policy cash floor, warning when cash does not cover the Client's stated liquidity needs. SR-05: direct holding of a restricted Instrument or sector is a breach; exposure to a restricted sector only through funds is a warning. SR-07 never breaches.
- Results are stored per run (`suitability_results`), returned as `suitability` on `GET /api/portfolios/{id}` and shown on the drill-down. Each is audited as `suitability_evaluated` (parent: run started); `priority_scored` lists it as a parent.
- Priority risk component = max(worst drift / breach threshold, suitability points), where suitability points are 50 per breaching rule and 15 per warning rule, capped at 100. Planted C001 now has risk 100 and C004 has 65; both outrank the clean Portfolio.
