# 09: Usage limits

**What to build:** Platform Owners can cap cost and abuse through config, and users see a plain message when they hit a limit. See spec: Limits.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] A Question over 2,000 characters returns `400`
- [ ] More than 50 Questions in a Conversation, or 20 per user per hour, returns `429` with a plain message
- [ ] All limits (Question length, per Conversation, per hour, history window, row budget) are settings with the `APP_` prefix
- [ ] The drawer shows the limit message and disables sending while the limit applies
