# 05: Failure, retry and the PII guard on replies

**What to build:** When the Assistant can't answer, the user sees a safe message and can retry, and the record has no gaps. A reply that somehow contains a Client name or email is never shown. See spec: Checks after the reply (PII), Solution (failure), API contract (retry).

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] A raising LLM produces a failed turn, an `assistant.failed` Audit Event (with the error Exchange reference when capture stored one) and a safe message with no exception text
- [ ] The drawer shows "The Assistant couldn't answer, try again" with a retry button; retry resubmits the same Question and screen identity as a new turn
- [ ] An Answer containing a Client name or email is rejected and treated as a failure
- [ ] An Exchange capture failure fails closed: no Answer reaches the user
- [ ] Manual E2E checklist item: retry works
