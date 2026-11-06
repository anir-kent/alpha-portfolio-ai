# 08: Suggested Questions and replay mode

**What to build:** Each screen offers three Suggested Questions whose Answers replay from committed recordings, so demos and tests work in the default recorded mode. Any other Question in recorded mode gets an honest "unavailable" message. Follow-up suggestions after an Answer are clickable. See spec: Replay mode, API contract (Suggested Questions).

**Blocked by:** 06, 07

**Status:** ready-for-agent

- [ ] Three Suggested Questions per screen kind, defined next to each Screen Context builder and served by the Suggested Questions endpoint
- [ ] Screen Context serialisation is byte-identical across repeat runs against the seeded data
- [ ] A recording script runs the Suggested Questions live against the seeded data with recording on, and its output is committed
- [ ] In recorded mode each Suggested Question replays its Answer; a free-form Question gives a failed turn and the message "only Suggested Questions work in replay mode"
- [ ] The drawer shows Suggested Questions and clickable follow-up suggestions
- [ ] Manual E2E checklist item: the replay-mode message shows
