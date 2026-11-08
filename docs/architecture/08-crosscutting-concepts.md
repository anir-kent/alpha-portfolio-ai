# 8. Crosscutting Concepts

The rules every component follows. Each subsection states the rule, where it is enforced, and the ADR that decides it. The tables between `GENERATED` markers are rendered from the live code by `uv run python -m scripts.architecture_doc regenerate`, and `check` fails in CI when they no longer match it. Do not edit them by hand.

## 8.1 Deterministic engine ownership

**Rule.** Deterministic code computes every number, Trade Line and suitability verdict. The LLM never produces one ([ADR-0001](../adr/0001-deterministic-engine-owns-numbers.md)).

The LLM has exactly three kinds of work, and each one has a deterministic gate:

| LLM work | What the model returns | What deterministic code does with it |
| --- | --- | --- |
| Extract Insights from a Report | Subject, direction, confidence, page, verbatim passage | Keeps an Insight only if its subject is in the platform's taxonomy and the passage really appears on the cited page. Every Insight starts pending, and only a Research Analyst's approval lets it count. |
| Propose a Research Tilt | Percentage points per approved Insight | Drops proposals for Insights it did not offer, ignores any part whose sign contradicts the Insight's direction, sums by subject and clips to the configured `tilt_bound_pp`. The rebalancer then computes the Trade Lines. |
| Explain (Recommendation memo, Queue narrative, Assistant Answer) | Claims, each with citations | Every Claim goes through the Grounding validator. Memos and Queue summaries are assembled from grounded Claims only. Flagged Claims stay visible, marked as flagged. |

Priority scores, drift, rebalancing, post-trade suitability and the approval plan are pure functions of the data and the config. A failing LLM step leaves the deterministic result exactly as it was: the Queue, the Recommendation and its Trade Lines all still stand.

## 8.2 Audit recording

**Rule.** Every business fact and every LLM call is written to one append-only, hash-chained audit trail through a single function. Nothing updates or deletes an Audit Event ([ADR-0002](../adr/0002-hash-chained-append-only-audit-log.md)).

- **One write path.** `audit.record` is the only writer. It rejects an event type that is not in the list below and a parent id that does not exist. Writes are serialised in the process, and each event is committed as it is written ([ADR-0009](../adr/0009-analysis-run-recording-commits-per-audit-event.md)).
- **Hash chain.** Each event's SHA-256 covers its type, actor (kind, name, role, model, prompt version), timestamp, payload, parent ids, subject ids and the previous event's hash. The first event chains from a fixed genesis hash. Editing, deleting or reordering any row breaks the chain at a findable row.
- **Actors.** A user actor carries a name and an RBAC role. A system actor carries the step's name and, for LLM steps, the model and prompt version.
- **Lineage.** Parent links connect Report passage, Insight, Research Tilt, Recommendation and Decision, with overrides flagged. The lineage view is derived from the chain and never writes to it.
- **LLM Exchanges.** An event produced by an LLM call carries the id and hash of the stored Exchange. Because the event's own hash covers that reference, verification recomputes the Exchange's hash and fails if the Exchange is missing or altered ([ADR-0004](../adr/0004-llm-exchanges-stored-separately-anchored-in-audit-chain.md)).
- **Verification.** `GET /api/audit/verify` (`audit:verify`) walks the whole chain and every referenced Exchange. It reports the first broken event or Exchange, and why.
- **Not audited.** Configuration changes (`PATCH /api/config`) are stored but write no Audit Event. Run Step progress is telemetry, not a business fact, and is never written to the chain ([ADR-0005](../adr/0005-run-step-progress-in-process.md)).

The Audit Event types the chain accepts:

<!-- BEGIN GENERATED: audit-event-types -->

| Audit Event type |
| --- |
| `report_ingested` |
| `insight_extracted` |
| `insight_approved` |
| `insight_rejected` |
| `analysis_run_started` |
| `priority_scored` |
| `suitability_evaluated` |
| `research_tilt_proposed` |
| `research_tilt_applied` |
| `recommendation_drafted` |
| `memo_generated` |
| `priority_narrative_generated` |
| `grounding_checked` |
| `claim_ungrounded` |
| `adversarial_fixtures_run` |
| `recommendation_modified` |
| `recommendation_superseded` |
| `decision_recorded` |
| `exception_approved` |
| `exception_blocked` |
| `access_denied` |
| `assistant.answered` |
| `assistant.refused` |
| `assistant.failed` |

<!-- END GENERATED: audit-event-types -->

## 8.3 LLM call shape and prompt versioning

**Rule.** Every LLM step is one schema-bound request and one JSON reply, through one interface. There is no agent framework, no agent loop, no tool calling and no retrieval over a vector store ([ADR-0007](../adr/0007-llm-steps-are-single-schema-bound-calls.md)).

- **Request.** A call names its task, its prompt version, the system text, the user prompt and the JSON schema of the reply. The live adapter sends one `POST chat/completions` with `response_format: json_schema`. The schema also travels in the system text. Through OpenRouter, the request asks only for providers that honour every parameter, so the reply schema is enforced. `temperature` is sent only when configured.
- **Reply.** The adapter parses one JSON object from the reply. The caller then validates it against its Pydantic model before using any of it. An unreadable reply is an LLM error, which the caller handles as a failed step.
- **Untrusted input.** Report text and Assistant Questions reach the model only in the user prompt, never in the system text. Insight extraction sends the Report's pages as plain `[Page N]` text. The Research Tilt prompt carries approved Insights' passages inside its JSON. Only the Assistant adds explicit fencing: its system text declares the Screen Context to be data, never instructions. In the Assistant prompt, Report passages and the text of other LLM Exchanges are fenced between `<<<…>>>` markers as JSON strings, to be quoted or described but never obeyed. Whatever the model makes of any input, its reply still passes the deterministic gates in [8.1](#81-deterministic-engine-ownership).
- **Credentials.** The API key travels only in the `Authorization` header. It is redacted from error messages and replies, and is never stored in an Exchange.
- **Prompt versions.** Each prompt has a name and a version, and the wording changes only with a version bump. The version is logged on every Exchange and Audit Event, and it is part of the recording key (see [8.4](#84-recorded-and-live-llm-modes)). A reworded prompt therefore misses its old recordings instead of silently replaying them. The Assistant's platform brief is versioned with `assistant_answer`.

<!-- BEGIN GENERATED: prompt-versions -->

| Prompt | Version | Logged as |
| --- | --- | --- |
| `insight_extraction` | `v1` | `insight_extraction@v1` |
| `research_tilt` | `v1` | `research_tilt@v1` |
| `recommendation_narrative` | `v1` | `recommendation_narrative@v1` |
| `priority_narrative` | `v1` | `priority_narrative@v1` |
| `assistant_answer` | `v3` | `assistant_answer@v3` |

<!-- END GENERATED: prompt-versions -->

## 8.4 Recorded and live LLM modes

**Rule.** The same code runs offline against recordings or online against an endpoint. `APP_LLM_MODE` chooses which, and both are captured the same way.

| Mode | Behaviour | Used for |
| --- | --- | --- |
| `recorded` (default) | Replays the reply stored under the call's key in `APP_LLM_RECORDINGS_DIR`. No network. A missing recording is an error, never a guess. | Tests, CI and the offline demo, against the committed recordings |
| `live` | Calls `APP_LLM_BASE_URL` with `APP_LLM_MODEL` (OpenRouter and `anthropic/claude-sonnet-5.5` by default). Refuses to start without `APP_LLM_API_KEY`. With `APP_LLM_RECORD=true`, saves each reply in the format recorded mode replays. | Real model runs, making new recordings, the live eval |

- **Recording key.** A SHA-256 over the task, prompt version, system text, reply schema and user prompt. Any change to the prompt or its inputs misses the recording, so a replay is always byte-exact.
- **Capture in both modes.** Every call, replayed or live, successful or failed, is stored as an LLM Exchange before the caller continues. If capture fails, the call fails ([ADR-0004](../adr/0004-llm-exchanges-stored-separately-anchored-in-audit-chain.md)). The mode is recorded on each Exchange.
- **Swapping the model** is a configuration change: any OpenAI-compatible endpoint, a LiteLLM gateway included. The committed recordings are keyed to the default model's replies. A different model needs new recordings or live mode.

## 8.5 SSE streaming

**Rule.** Live progress is pushed as server-sent events (`text/event-stream`). The browser reconnects with its last event id, and the server never assumes a connection lasts.

| Stream | Events | Ends |
| --- | --- | --- |
| `GET /api/analysis/runs/{id}/events` (`analysis:run`) | The run's full snapshot (Run Steps, Portfolios scored, outcome) as a `progress` event, on connect and whenever it has changed, checked every `APP_LLM_STREAM_POLL_SECONDS`. The event id is the run's sequence number, and an unchanged snapshot is never sent twice. | After the snapshot carrying the outcome, or after `APP_LLM_STREAM_MAX_SECONDS`; the browser reconnects |
| `GET /api/llm/exchanges/stream` (`llm:read`) | Each new LLM Exchange in id order, found by polling the store every `APP_LLM_STREAM_POLL_SECONDS` | After `APP_LLM_STREAM_MAX_SECONDS`; the browser reconnects |

Both streams work the same way. Each polls rather than being pushed to, sends a keepalive comment after 15 seconds without an event, and reads `Last-Event-ID` as a number (anything else is ignored). Both also send headers that stop caching and proxy buffering. Each stream gives back its request's database session and polls on short-lived sessions of its own. Run Step progress is held in process memory, so it streams only from the process that runs the Analysis Run ([ADR-0005](../adr/0005-run-step-progress-in-process.md)).

## 8.6 Configuration service

**Rule.** Business parameters live in one validated configuration, read by every engine at the moment it runs.

- **Shape.** One Pydantic model: Tolerance Bands per Risk Profile, priority weights (which must sum to 1), the Research Tilt bound, the review SLA, approval thresholds and Suitability limits. Stored values are kept per top-level key in the database and validated on every read.
- **Changes.** The Platform Owner changes it through `PATCH /api/config` (`config:write`). Only the keys supplied change. Tolerance Bands merge per Risk Profile: a supplied band replaces that profile's whole band. Suitability limits merge per field, and per Risk Profile within the per-profile maps. The result is validated before it is stored. `config:read` roles can read it.
- **Effect.** Nothing is cached. The next Analysis Run, read or Decision uses the new values. That includes re-planning the tiered approvals ([5.2](05-building-block-view.md#tiered-approval-policy)). Configuration changes write no Audit Event (see [8.2](#82-audit-recording)).
- **Not configuration.** Process settings (database URL, LLM mode, endpoint and key, cookie and session settings, Assistant limits, file locations) are `APP_`-prefixed environment variables, read once at start-up. Secrets come only from the environment or a git-ignored `.env` file.

Defaults of a fresh database:

<!-- BEGIN GENERATED: config-defaults -->

| Setting | Default |
| --- | --- |
| `tolerance_bands.conservative` | warn 2, breach 4 |
| `tolerance_bands.moderate` | warn 3, breach 5 |
| `tolerance_bands.growth` | warn 4, breach 6 |
| `tolerance_bands.aggressive` | warn 5, breach 8 |
| `priority_weights` | drift 0.4, risk 0.3, opportunity 0.2, urgency 0.1 |
| `tilt_bound_pp` | 2 |
| `sla_days` | 30 |
| `approval_thresholds` | turnover_pct 15, trade_line_pct 10 |
| `suitability.max_equity_pct` | conservative 30, moderate 55, growth 80, aggressive 95 |
| `suitability.single_position_pct` | 10 |
| `suitability.sector_pct` | 30 |
| `suitability.min_cash_pct` | conservative 5, moderate 3, growth 2, aggressive 1 |
| `suitability.horizon_short_years` | 5 |
| `suitability.horizon_short_equity_max_pct` | 40 |
| `suitability.taxable_gain_pct` | 15 |
| `suitability.warn_ratio` | 0.9 |

<!-- END GENERATED: config-defaults -->

## 8.7 Idempotent migrations

**Rule.** The schema is the SQLAlchemy models, plus hand-written migrations that are safe to run on every start ([ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md)).

On start, the API process creates any missing tables. It then runs each migration in a fixed order. Each one inspects the schema first and does nothing when its change is already there, so the same sequence works on a new database and on an old one. A migration that SQLite cannot do in place, such as dropping a `NOT NULL` constraint, rebuilds the table inside one transaction and copies every row across. There is no migration framework and no down-migration. A new schema change adds one more such function to the start-up sequence.

## 8.8 Authentication and authorization

**Rule.** The server is the only enforcement point. The SPA hides what a role cannot use, but that hiding is cosmetic.

- **Login.** Users are seeded, one per role. Passwords are hashed with scrypt (random 16-byte salt, compared in constant time). A successful login issues an opaque random token in a cookie that is `HttpOnly`, `SameSite=Lax` and path `/`. Only the token's SHA-256 is stored server-side, with an expiry `APP_SESSION_TTL_HOURS` ahead (12 by default). The cookie's `Secure` flag follows `APP_COOKIE_SECURE`, which is off by default.
- **Session.** Each request resolves the cookie to an unexpired session. An expired session is deleted when it is next seen, and its Assistant Conversation is ended. Logout deletes the session row, ends the Conversation and clears the cookie.
- **Authorization.** Every endpoint except login, logout, the session lookup (`/api/auth/me`) and the liveness probe requires a permission. A role lacking it gets 403, and an `access_denied` Audit Event records the user, the permission, the method and the path.
- **Matrix.** The role × permission matrix below is generated from the code. Every role holds `assistant:use`. What the Assistant sees is still limited by the role's other permissions.

<!-- BEGIN GENERATED: rbac-matrix -->

| Permission | `relationship_manager` | `advisor` | `portfolio_manager` | `research_analyst` | `compliance_officer` | `investment_committee` | `auditor` | `platform_owner` |
| --- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `analysis:run` | ✓ | ✓ |  |  |  |  |  |  |
| `approvals:read` |  |  |  |  | ✓ | ✓ |  |  |
| `assistant:use` | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `audit:read` |  |  |  |  |  |  | ✓ |  |
| `audit:verify` |  |  |  |  |  |  | ✓ |  |
| `client:pii` |  | ✓ |  |  | ✓ |  |  |  |
| `committee:decide` |  |  |  |  |  | ✓ |  |  |
| `compliance:decide` |  |  |  |  | ✓ |  |  |  |
| `config:read` |  |  | ✓ |  | ✓ |  | ✓ | ✓ |
| `config:write` |  |  |  |  |  |  |  | ✓ |
| `governance:read` |  |  |  |  |  |  | ✓ | ✓ |
| `governance:run` |  |  |  |  |  |  | ✓ | ✓ |
| `grounding:read` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |
| `grounding:validate` | ✓ | ✓ |  |  |  |  |  |  |
| `health:read` |  |  |  |  |  |  |  | ✓ |
| `insight:approve` |  |  |  | ✓ |  |  |  |  |
| `insight:read` | ✓ | ✓ | ✓ | ✓ | ✓ |  | ✓ |  |
| `llm:read` |  |  |  |  | ✓ |  | ✓ | ✓ |
| `portfolio:read` | ✓ | ✓ | ✓ |  | ✓ |  | ✓ |  |
| `queue:read` | ✓ | ✓ |  |  |  |  |  |  |
| `recommendation:decide` | ✓ | ✓ |  |  |  |  |  |  |
| `recommendation:read` | ✓ | ✓ | ✓ |  | ✓ | ✓ | ✓ |  |
| `report:read` |  |  |  | ✓ |  |  |  |  |
| `report:upload` |  |  |  | ✓ |  |  |  |  |

<!-- END GENERATED: rbac-matrix -->

## 8.9 PII stance

**Rule.** Client names and emails never leave the platform in a prompt. Only the roles that need them see them on screen.

- **Synthetic data.** All Clients are synthetic and seeded. Even so, their name and email are treated as the sensitive fields ([ADR-0003](../adr/0003-market-data-snapshot-synthetic-clients.md)).
- **On screen.** Only `client:pii` shows them. The Advisor and the Compliance Officer hold it. For every other role, the Queue, Portfolio and Approvals responses return the fields empty.
- **In prompts.** LLM steps and Screen Contexts identify a Client by its id (for example `C003`), never by name or email. That holds even for a user who holds `client:pii`.
- **On replies.** Before an Assistant Answer is checked, stored or shown, it is searched for every Client's name and email, case-insensitively. A hit turns the turn into a failure, and the Answer is discarded.
- **Guarding tests.** One test asserts that no captured prompt from a full Analysis Run and Report ingestion contains any Client's name, surname or email. Others assert the same for the Assistant's prompts on the Queue and Recommendation screens and for an Advisor holding `client:pii`, and that a leaking Answer is rejected.

## 8.10 Assistant usage limits

**Rule.** The Assistant is bounded per Question, per Conversation and per user-hour, and in how much context each prompt carries. A refused Question is answered with 400 or 429 and a plain message. The limits are process settings, generated from their defaults:

<!-- BEGIN GENERATED: assistant-limits -->

| Setting | Default | Effect |
| --- | --- | --- |
| `APP_ASSISTANT_HISTORY_PAIRS` | 6 | Question/Answer pairs of earlier turns sent with each Question |
| `APP_ASSISTANT_CONTEXT_ROWS` | 25 | Rows of a list screen (the Queue) a Screen Context holds, by the screen's sort |
| `APP_ASSISTANT_QUESTION_MAX_CHARS` | 2000 | A longer Question is refused with 400 |
| `APP_ASSISTANT_QUESTIONS_PER_CONVERSATION` | 50 | Questions a Conversation takes; then 429 until the next login |
| `APP_ASSISTANT_QUESTIONS_PER_HOUR` | 20 | Questions a user may ask in any rolling hour; then 429 |

<!-- END GENERATED: assistant-limits -->
