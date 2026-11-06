# 10: Guardrail eval set and model card entry

**What to build:** Maintainers can catch guardrail regressions before bumping the prompt version, and governance covers the Assistant like every other LLM use. See spec: Testing Decisions (eval set), Governance.

**Blocked by:** 04, 05, 06

**Status:** ready-for-agent

- [ ] A committed eval set of in-scope SME Questions, out-of-scope Questions (advice, predictions, unrelated topics, another Client's id) and prompt-injection Report passages
- [ ] CI runs the deterministic guards (refusal path, PII guard, grounding, permission filtering) over the eval set using recorded or scripted replies
- [ ] A live eval script (run by hand, not in CI) reports the refusal rate and the ungrounded-Claim rate
- [ ] The governance model card lists the Assistant: prompt version, scope policy summary, limits and latest eval results
