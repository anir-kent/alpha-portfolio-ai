# 8. Crosscutting Concepts

The rules every component follows. Each subsection states the rule, where it is enforced, and the ADR that decides it. The tables between `GENERATED` markers are rendered from the live code by `uv run python -m scripts.architecture_doc regenerate`, and `check` fails in CI when they no longer match it. Do not edit them by hand.

## 8.1 Deterministic engine ownership

**Rule.** Deterministic code computes every number, Trade Line and suitability verdict. The LLM never produces one ([ADR-0001](../adr/0001-deterministic-engine-owns-numbers.md)).

[Detailed 8.1 deterministic engine ownership implementation detail](appendices.md#e22-81-deterministic-engine-ownership-implementation-detail).

## 8.2 Audit recording

**Rule.** Business evidence is written to one append-only, hash-chained audit trail through a single function; each captured LLM Trajectory is anchored by Exchange id and hash. Configuration changes are not audited, a no-Trade-Line tilt can lack an anchor (TD-03), and failed scoring can roll back its Exchanges (TD-04). Interrupted recording can leave incomplete evidence (TD-05). Nothing updates or deletes an Audit Event ([ADR-0002](../adr/0002-hash-chained-append-only-audit-log.md)).

[Detailed 8.2 audit recording implementation detail](appendices.md#e23-82-audit-recording-implementation-detail).

## 8.3 LLM call shape and prompt versioning

**Rule.** Every LLM step runs on pydantic-ai through one captured interface, and its final reply is one JSON object held to the step's schema. The four pipeline steps are one request with no tools. The Assistant is the one agent: a bounded loop of read-only lookups and at most one self-correction, capped at `APP_ASSISTANT_REQUEST_LIMIT` requests. There are no write tools, no multi-agent delegation and no retrieval over a vector store ([ADR-0010](../adr/0010-assistant-is-a-bounded-read-only-agent-on-pydantic-ai.md), superseding ADR-0007).

[Detailed 8.3 llm call shape and prompt versioning implementation detail](appendices.md#e24-83-llm-call-shape-and-prompt-versioning-implementation-detail).

<!-- BEGIN GENERATED: prompt-versions -->

| Prompt | Version | Logged as |
| --- | --- | --- |
| `insight_extraction` | `v1` | `insight_extraction@v1` |
| `research_tilt` | `v1` | `research_tilt@v1` |
| `recommendation_narrative` | `v1` | `recommendation_narrative@v1` |
| `priority_narrative` | `v1` | `priority_narrative@v1` |
| `assistant_answer` | `v5` | `assistant_answer@v5` |

<!-- END GENERATED: prompt-versions -->

## 8.4 Recorded and live LLM modes

**Rule.** The same code runs offline against recordings or online against an endpoint. `APP_LLM_MODE` chooses which, and both are captured the same way.

[Detailed 8.4 recorded and live llm modes implementation detail](appendices.md#e25-84-recorded-and-live-llm-modes-implementation-detail).

## 8.5 SSE streaming

**Rule.** Live progress is pushed as server-sent events (`text/event-stream`). The browser reconnects with its last event id, and the server never assumes a connection lasts.

[Detailed 8.5 sse streaming implementation detail](appendices.md#e26-85-sse-streaming-implementation-detail).

## 8.6 Configuration service

**Rule.** Business parameters live in one validated configuration, read by every engine at the moment it runs.

[Detailed 8.6 configuration service implementation detail](appendices.md#e27-86-configuration-service-implementation-detail).

## 8.7 Idempotent migrations

**Rule.** The schema is the SQLAlchemy models, plus hand-written migrations that are safe to run on every start ([ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md)).

[Detailed 8.7 idempotent migrations implementation detail](appendices.md#e28-87-idempotent-migrations-implementation-detail).

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

**Rule.** Application-derived Client fields use pseudonymous ids in prompts and Screen Contexts. Only the roles that need names and emails see those fields on screen. This is not a general input sanitizer: arbitrary Questions, Conversation history and uploaded Reports can contain sensitive text that leaves for the provider in live mode and remains in Exchanges ([Appendix D](appendices.md#secrets-and-sensitive-data)).

- **Synthetic data.** All Clients are synthetic and seeded. Even so, their name and email are treated as the sensitive fields ([ADR-0003](../adr/0003-market-data-snapshot-synthetic-clients.md)).
- **On screen.** Only `client:pii` shows them. The Advisor and the Compliance Officer hold it. For every other role, the Queue, Portfolio and Approvals responses return the fields empty.
- **In prompts.** When LLM steps and Screen Contexts populate Client identity from application records, they use its id (for example `C003`), rather than its name or email. That holds even for a user who holds `client:pii`; it does not remove sensitive text supplied in free-form input.
- **On replies.** Before an Assistant Answer is checked, stored or shown, it is searched for every Client's name and email, case-insensitively. A hit turns the turn into a failure, and the Answer is discarded.
- **Guarding tests.** One test asserts that no captured prompt from a full Analysis Run and Report ingestion contains any Client's name, surname or email. Others assert the same for the Assistant's prompts on the Queue and Recommendation screens and for an Advisor holding `client:pii`, and that a leaking Answer is rejected.

## 8.10 Assistant usage limits

**Rule.** The Assistant is bounded per Question, per Conversation and per user-hour, and in how much context each prompt carries. A refused Question is answered with 400 or 429 and a plain message. The limits are process settings, generated from their defaults:

[Detailed assistant usage limits](appendices.md#e13-assistant-usage-limits).
