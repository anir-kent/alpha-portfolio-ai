# 05: Portfolio drill-down

**What to build:** An Advisor opens a Portfolio and sees Holdings, an actual-vs-target allocation chart per Asset Class with drift against bands, Portfolio Drift, the Client's Risk Profile, objectives, horizon, liquidity needs and Restrictions, and look-through sector exposure including via funds. Sensitive Client fields are masked by role.

**Blocked by:** 04

**Status:** done

**Carry-forward from 04:** Portfolio Manager lost `queue:read` and currently has no way to read Portfolio or drift data; spec story 51 expects a read-only route. Add it here (`portfolio:read`). Per-class drift and status are already computed in `app/analysis.py` and stored per run.

- [x] Look-through exposure matches the reference weights on the planted scenarios
- [x] Allocation chart and drift display agree with API values
- [x] Relationship Manager role sees masked sensitive fields; roles without access are denied and audited
- [x] Version/Decision history section exists (empty until later tickets)

## Implementation notes

- `GET /api/portfolios/{id}` (`portfolio:read`): Holdings, look-through sector exposure (total / direct / via funds), Client context, Restrictions, drift from the latest completed run (null before any run), empty `history`. Name and email are masked (null) without `client:pii`.
- `portfolio:read` was already granted to Portfolio Manager in `app/rbac.py`; the carry-forward gap was only the missing route, now added.
- Drift is read from the stored run, so it always agrees with the queue; holdings and exposure are live at the snapshot prices.
