# 10: Guardrail eval set and model card entry

**What to build:** Maintainers can catch guardrail regressions before bumping the prompt version, and governance covers the Assistant like every other LLM use. See spec: Testing Decisions (eval set), Governance.

**Blocked by:** 04, 05, 06

**Status:** ready-for-agent

- [ ] A committed eval set of in-scope SME Questions, out-of-scope Questions (advice, predictions, unrelated topics, another Client's id) and prompt-injection Report passages
- [ ] CI runs the deterministic guards (refusal path, PII guard, grounding, permission filtering) over the eval set using recorded or scripted replies
- [ ] A live eval script (run by hand, not in CI) reports the refusal rate and the ungrounded-Claim rate
- [ ] The governance model card lists the Assistant: prompt version, scope policy summary, limits and latest eval results

## Comments

**From ticket 08.** The eval should cover platform-only Questions (Config, Health, Exchanges with nothing selected). `assistant_answer@v1` has no way to cite the PLATFORM BRIEF. While recording, `gpt-4.1-mini` invented citation kinds (`platform`, `platform_brief`), which gave failed turns (`unreadable_reply`), or cited `"PLATFORM BRIEF"` as an engine figure, which gave ungrounded Claims. Consider an `assistant_answer@v2` that keeps platform explanations Claim-free, then re-record with `uv run python -m tests.fixtures.suggested_questions`.
