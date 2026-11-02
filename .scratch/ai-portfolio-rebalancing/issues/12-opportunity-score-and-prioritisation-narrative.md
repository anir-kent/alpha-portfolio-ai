# 12: Opportunity score and prioritisation narrative

**What to build:** The Opportunity component of the priority score, computed from a Portfolio's look-through exposure to sectors with approved Insights. Each queue row also shows a short, cited "why this client, why now" narrative from the LLM built from the score breakdown and relevant Insights, validated by the grounding validator. The score itself stays deterministic.

**Blocked by:** 04, 10

**Status:** ready-for-agent

- [ ] Opportunity is 0 without approved Insights and increases with relevant exposure
- [ ] The LLM does not influence any score or ranking
- [ ] Narrative claims are grounded or flagged; flagged claims are not shown as fact
- [ ] Narrative generation is audited
