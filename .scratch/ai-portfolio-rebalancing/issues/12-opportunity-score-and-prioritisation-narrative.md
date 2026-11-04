# 12: Opportunity score and prioritisation narrative

**What to build:** The Opportunity component of the priority score, computed from a Portfolio's look-through exposure to sectors with approved Insights. Each queue row also shows a short, cited "why this client, why now" narrative from the LLM built from the score breakdown and relevant Insights, validated by the grounding validator. The score itself stays deterministic.

**Blocked by:** 04, 10

**Status:** done

**Carry-forward from 04:** `score_portfolio` already takes an `opportunity` argument (0-100, default 0) and returns it in the breakdown; `run_analysis` doesn't pass it yet. With opportunity at 0 the max score is 80. `DRIFT_FULL_PP` and the 70/40 label cut-offs are code constants; move to config here if wanted.

- [x] Opportunity is 0 without approved Insights and increases with relevant exposure
- [x] The LLM does not influence any score or ranking
- [x] Narrative claims are grounded or flagged; flagged claims are not shown as fact
- [x] Narrative generation is audited

**Implemented:** `app/opportunity.py` (exposure to sectors with an approved positive/negative Insight, each counted once, saturating at 30% of Portfolio value); `app/priority_narrative.py` (cited narrative per queue row, only for Portfolios holding a sector with a relevant approved Insight); `grounding.validate_figures` generalises the validator to any engine figure set (`GroundingResultRow.recommendation_id` is now nullable, new `run_id`; existing dev databases need recreating). Audit event `priority_narrative_generated`. `DRIFT_FULL_PP`, `OPPORTUNITY_FULL_PCT` and the 70/40 cut-offs remain code constants.
