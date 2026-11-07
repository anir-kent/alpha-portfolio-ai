# 09: Usage limits

**What to build:** Platform Owners can cap cost and abuse through config, and users see a plain message when they hit a limit. See spec: Limits.

**Blocked by:** 02

**Status:** resolved

- [x] A Question over 2,000 characters returns `400`
- [x] More than 50 Questions in a Conversation, or 20 per user per hour, returns `429` with a plain message
- [x] All limits (Question length, per Conversation, per hour, history window, row budget) are settings with the `APP_` prefix
- [x] The drawer shows the limit message and disables sending while the limit applies

## Comments

**Open from code review (not fixed here).**

- After a page reload the drawer forgets a limit. The first send gets the `429` again and then disables sending. Fixing it needs the limit state on `GET /api/assistant/conversation`.
- Limits are checked before the model call and the turn is stored after it, so requests in flight at the same time (two tabs, a script) can each pass the check. Closing that needs a reserved slot or a re-count inside the write.
- The rolling-hour tests move turns back in time through the database. `CODING_STANDARDS.md` asks for time to be controlled through dependency overrides, and there is no clock override yet.
- Limit hits are not audited (recorded in ADR-0006). Ticket 10 should list the limits on the model card.
