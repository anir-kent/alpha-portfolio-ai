# 11: AI-assisted Recommendations

**What to build:** The LLM assesses how approved Insights affect a Portfolio via look-through exposure, proposes a Research Tilt, and the engine clips it to configured bounds (default plus or minus 2 percentage points) before it influences Trade Lines. The Recommendation shows "AI proposed X, engine allowed Y", a cited rationale and an advisor memo, with ungrounded claims flagged and excluded from the memo.

**Blocked by:** 07, 10

**Status:** ready-for-agent

- [ ] Tilt never exceeds bounds; both proposed and allowed tilt are recorded in the audit chain
- [ ] Numbers in rationale and memo come from the engine; the LLM does not produce numbers or compliance outcomes
- [ ] Only approved Insights can influence a tilt
- [ ] Memo generation and flags are audited with model and prompt version
- [ ] Recommendation panel shows citations, proposed-versus-allowed tilt and grounding flags
