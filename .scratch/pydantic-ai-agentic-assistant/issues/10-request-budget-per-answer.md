# 10: Request budget per Answer

**What to build:** An Answer can never run away. Each Answer may use at most N model requests (a setting, default 6, token limits off). Going over fails the turn with the new reason `budget_exhausted` and a user-facing message suggesting a narrower Question. Every Exchange the turn made stays anchored in its `assistant.failed` event. "How I answered" shows requests used against the limit. Spec: "Assistant agent → Budget".

**Blocked by:** 07 (Assistant tracer bullet: one lookup, end to end)

**Status:** resolved

- [x] The request limit is configurable in settings, defaults to 6, and is shown on the Governance model card if similar limits already appear there
- [x] Exceeding it fails the turn with `budget_exhausted`, stored with the turn so a reload shows the same message
- [x] `assistant.failed` anchors every Exchange made, in order, and chain verification passes
- [x] The turn's `trajectory` summary reports `requests_used` and `request_limit` for successful and failed turns
- [x] Tests (scripted Model that keeps calling tools): the turn fails at the limit with all Exchanges anchored; a turn under the limit is unaffected
