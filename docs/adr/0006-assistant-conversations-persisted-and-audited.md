# Assistant Conversations are persisted server-side, append-only and anchored in the audit chain

"Store the conversation history during the active session" is read as: a Conversation belongs to one login session (the server-side session row) and the user can continue it until logout or expiry, but its turns are never deleted. Each turn is an append-only row holding the Question, the screen identity, a hash of the Screen Context the server built, the Answer and its grounding verdict, and a reference to the LLM Exchange; each turn also writes an `assistant.answered` or `assistant.refused` Audit Event pointing at that Exchange. Compliance officers and auditors therefore review Conversations through the existing Exchange and Audit views; no new browsing screen exists.

## Considered Options

- **Browser-memory history only**: rejected. Lost on reload, invisible to compliance, and the Exchanges would still be kept (ADR-0004), leaving model calls whose surrounding conversation cannot be reconstructed.
- **Server-side but deleted at logout**: rejected. Contradicts the no-deletion stance of ADR-0002 and ADR-0004 for anything an LLM said to an Advisor.
- **Resumable across logins**: rejected for v1. "Active session" scopes the requirement, and cross-session memory widens what a prompt can carry.

## Consequences

A turn that fails writes `assistant.failed`, with the error Exchange's reference when capture stored one. A Question about an entity the user cannot read, or one that does not exist, is refused without calling the model, so its `assistant.refused` event carries no Exchange reference and its turn no Screen Context hash; verification treats it like any event without a reference. History reaches the model as a labelled transcript block inside the single `user` prompt (last N Question/Answer pairs, text only), so the LLM interface, recording key and Exchange capture are unchanged. Screen Contexts carry Client ids and pseudonyms only, never names or emails, even for users holding `client:pii`, so ADR-0004's prompt-PII guard still holds. A Suggested Question is the one exception to the history block: it is sent without the Conversation so far, so its prompt depends only on the screen and its data and its committed recording replays whatever was asked before it. A failed turn stores its reason (`llm_error`, `unreadable_reply`, `pii` or `replay_miss`) alongside the outcome, so a reload shows the same message: a recorded-mode miss says that only Suggested Questions work in replay mode.
