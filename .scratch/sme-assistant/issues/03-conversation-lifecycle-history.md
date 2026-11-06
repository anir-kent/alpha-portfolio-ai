# 03: Conversation lifecycle and history

**What to build:** The Conversation behaves as one continuous thread for the login session. It survives reloads and screen changes, sends recent history to the model so follow-up Questions work, marks context changes, and ends at logout. See spec: Conversation and persistence, Prompt and LLM call (history), API contract (read).

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Reading the current Conversation returns its turns in order, and returns `204` before the first Question
- [ ] The drawer restores the Conversation after a page reload
- [ ] The prompt carries the last N Question/Answer pairs (default 6, configurable) as a labelled transcript, text only, with no earlier Screen Contexts; after 8 turns only the last 6 appear
- [ ] Each turn keeps the screen identity it was asked against; the drawer shows a "context changed" divider when it changes
- [ ] Logout or session expiry ends the Conversation; the next login starts a new one and the old one can't be resumed
- [ ] Ended Conversations' turns are still stored and still verify in the audit chain
- [ ] Manual E2E checklist items: reload restores the Conversation, the divider appears, logout clears it
