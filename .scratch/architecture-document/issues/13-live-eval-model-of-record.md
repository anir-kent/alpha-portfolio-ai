# 13: Live eval on the model of record

**What to build:** The AI Governance appendix and live model card show eval results measured on the model of record, `anthropic/claude-sonnet-5.5` via OpenRouter, and never on another model.

**Blocked by:** 10

**Status:** resolved

- [x] Live eval run against the model of record (done in ai-portfolio-rebalancing ticket 15)
- [x] Eval results file reports `anthropic/claude-sonnet-5.5`, `assistant_answer@v3`
- [ ] Appendix results confirmed to match the eval results file and the Governance page model card (verified as part of ticket 10 and ticket 12)

## Comments

2026-11-07: Resolved before work started. Ticket 15 of ai-portfolio-rebalancing re-ran the live eval on the model of record: 30/30 passed, refusal rate 1.0, false-refusal rate 0.0, ungrounded-claim rate 0.17, injection leaks 0, failed turns 0, run at 2026-11-07T14:03Z. The remaining confirmation moves into ticket 10's and ticket 12's acceptance criteria. Ticket 14 is no longer gated by a human step.
