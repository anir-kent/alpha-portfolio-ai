# 09: Self-correction against the guardrails

**What to build:** When the Assistant's first draft contains ungrounded Claims, it is told which Claims failed and why and gets one chance to correct itself. "How I answered" shows that self-correction happened. A draft that would expose PII is rejected outright and never coached. An output validator runs the existing PII check, then grounding, on each candidate reply. Spec: "Assistant agent → Output validator"; ADR-0010.

**Blocked by:** 07 (Assistant tracer bullet: one lookup, end to end)

**Status:** resolved

- [x] A PII hit ends the run and fails the turn with reason `pii`, with no retry
- [x] Ungrounded Claims raise a model retry whose message lists each failing Claim and its issue. The output retry budget is exactly 1
- [x] On the final attempt, ungrounded Claims are accepted and shown flagged, as today
- [x] Only the final Answer's grounding check is stored as the turn's `grounding_check_id`. The rejected draft's feedback is visible verbatim in the retry Exchange
- [x] "How I answered" shows a self-correction step with the issue count
- [x] Tests (scripted Model): ungrounded then grounded produces one retry carrying the issue list and a grounded Answer; ungrounded twice keeps the Claims flagged and never makes a third attempt; PII on the first draft fails with `pii` and makes exactly one request
