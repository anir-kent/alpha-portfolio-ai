# 11: AI-assisted Recommendations

**What to build:** The LLM assesses how approved Insights affect a Portfolio via look-through exposure, proposes a Research Tilt, and the engine clips it to configured bounds (default plus or minus 2 percentage points) before it influences Trade Lines. The Recommendation shows "AI proposed X, engine allowed Y", a cited rationale and an advisor memo, with ungrounded claims flagged and excluded from the memo.

**Blocked by:** 07, 10

**Status:** done

- [x] Tilt never exceeds bounds; both proposed and allowed tilt are recorded in the audit chain
- [x] Numbers in rationale and memo come from the engine; the LLM does not produce numbers or compliance outcomes
- [x] Only approved Insights can influence a tilt
- [x] Memo generation and flags are audited with model and prompt version
- [x] Recommendation panel shows citations, proposed-versus-allowed tilt and grounding flags

## Implementation notes

- `app/research_tilt.py`: the LLM sees only approved Insights plus engine look-through exposure and returns a tilt per Insight. The engine drops unknown ids, ignores the part contradicting the Insight direction, sums per subject and clips to `tilt_bound_pp` (`clip_tilt`). Stacked Asset-Class tilts are scaled back so no target moves more than the bound.
- Asset-Class tilts shift the target the rebalancer aims at; sector tilts are a switch inside equity (`rebalance.sector_sleeve`, SPY <-> sector ETF in the same Account, limited to what is held). Tolerance and post-trade drift still use the real Target Allocation.
- A tilt only influences Trade Lines when the Portfolio is already outside tolerance. A sector tilt the sleeve cannot trade (no SPY held, restriction, rounding) is still recorded as allowed.
- `app/narrative.py`: LLM claims go through the grounding validator; the memo is assembled by the engine from engine figures plus grounded claims only. Tilt figures (`tilt.<subject>.proposed_pp|allowed_pp|exposure_pct`) are citable.
- Audit: `research_tilt_proposed` (LLM actor with model and prompt version), `research_tilt_applied` (proposed and allowed, parented on the proposal), `memo_generated` (model and prompt version), plus the existing grounding events. LLM failure at either step is audited and falls back to the plain rule-based Recommendation.
- Not done: modified versions (v2+) carry no AI section; recorded LLM replies for the demo are not authored (recorded mode falls back to no tilt until ticket 15).
