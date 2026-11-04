# 10: Grounding validator

**What to build:** Validation of every LLM claim: a citation (Report ID, page and quote, or a named engine figure) is required, the quote must appear in the cited passage, and every number must match engine figures. Invalid or uncited claims are flagged ungrounded, kept out of memos, and still visible to the Advisor.

**Blocked by:** 09

**Status:** done

- [x] Adversarial fixtures (fabricated quote, wrong number, uncited asset call) are caught
- [x] Valid claims pass with their citation intact
- [x] Flags are returned through the API and recorded as audit events
- [x] Grounding results are stored so the AI quality panel can aggregate them later
