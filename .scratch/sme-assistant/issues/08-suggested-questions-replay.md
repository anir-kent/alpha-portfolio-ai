# 08: Suggested Questions and replay mode

**What to build:** Each screen offers three Suggested Questions whose Answers replay from committed recordings, so demos and tests work in the default recorded mode. Any other Question in recorded mode gets an honest "unavailable" message. Follow-up suggestions after an Answer are clickable. See spec: Replay mode, API contract (Suggested Questions).

**Blocked by:** 06, 07

**Status:** resolved

- [x] Three Suggested Questions per screen kind, defined next to each Screen Context builder and served by the Suggested Questions endpoint
- [x] Screen Context serialisation is byte-identical across repeat runs against the seeded data
- [x] A recording script runs the Suggested Questions live against the seeded data with recording on, and its output is committed
- [x] In recorded mode each Suggested Question replays its Answer; a free-form Question gives a failed turn and the message "only Suggested Questions work in replay mode"
- [x] The drawer shows Suggested Questions and clickable follow-up suggestions
- [x] Manual E2E checklist item: the replay-mode message shows

## Comments

**Implemented.** Decisions made during the work:
- **Audit can't replay** (decided with the user). Audit Events carry wall-clock timestamps and chain hashes, and each Assistant turn adds one, so the Audit Screen Context is kept faithful and never matches a recording. Audit still serves three Suggested Questions; in recorded mode they get the replay-mode message. Tested and documented. Every other screen kind is byte-identical across freshly seeded databases (`test_every_demo_screen_context_is_byte_identical_across_freshly_seeded_databases`).
- **A Suggested Question is sent without the Conversation so far**, so its recording replays whatever was asked before it (ADR-0006 amended).
- **A failed turn stores `failure_reason`**, a new column with an in-place migration. A recorded miss is `replay_miss` and reads "Only Suggested Questions work in replay mode." on ask and after reload (spec amended).
- **Test settings ignore the developer's `.env`** (`replay_settings`). The Governance context names the model and endpoint, so it has to match CI.
- **Recordings** live in `tests/fixtures/llm` and come from `uv run python -m tests.fixtures.suggested_questions`: 45 distinct prompts across the demo screens and every role. They were recorded with the live model configured in `.env` (`gpt-4.1-mini`), so the recorded model differs from the default model the replayed Governance card names.
- **Seven Suggested Questions were reworded** while recording. Some fell outside the platform brief, and the model refused them or invented definitions. On others the model invented a `"platform"` citation kind, which the reply schema rejects.

**Follow-up for ticket 10.** `assistant_answer@v1` gives the model no way to cite the PLATFORM BRIEF. So on Config, Health and Exchanges answers it either invents a citation kind (an unreadable reply, so a failed turn) or cites `"PLATFORM BRIEF"` as an engine figure (an ungrounded Claim). A v2 prompt should say that platform explanations go in `answer_markdown` with no Claims, or allow a brief citation. Then re-record.
