Status: ready-for-agent

# Assistant: a read-only, grounded conversational helper on every screen

Vocabulary follows `GLOSSARY.md`. The new terms are in its **Assistant** section: **Assistant**, **Conversation**, **Question**, **Answer**, **Screen Context**, **Suggested Question** and **Out-of-Scope Refusal**. Decisions respect `docs/adr/0001` to `0005` and the new `0006-assistant-conversations-persisted-and-audited`.

## Problem Statement

The platform shows subject matter experts a lot of data: Advisors, Portfolio Managers, Compliance Officers, Research Analysts and Auditors all see it. That data includes drift and priority figures, Trade Lines, Suitability outcomes, Research Tilts, Insights with their Report passages, grounding verdicts, Audit Events and LLM Exchanges. It does not let them ask about that data.

The questions an SME has are rarely about one number. They look like these:
- "Why is this Portfolio ranked above that one?"
- "Which Restriction caused this Suitability warning?"
- "Which Report passage drove the tilt toward technology?"
- "What did the model see when it wrote this memo?"

Today the SME answers these by clicking across several screens and assembling the answer in their head. A general-purpose chatbot would be worse than nothing. It would invent figures, which breaks ADR-0001. It would see data the user can't, which breaks the RBAC matrix. It would leak Client names into prompts, which breaks ADR-0004. And it would drift into investment advice the platform must never give.

## Solution

A collapsible **Assistant** drawer is available on every screen and stays open across navigation. Its header names the current Screen Context, for example "Portfolio P-0042" or "Recommendation R-17, Trade Line 3". The user types a Question, or clicks one of three Suggested Questions for that screen.

The browser sends the Question and the screen's identity: route, entity ids and an optional selected item. The server rebuilds the Screen Context from the database, using the same services the screen itself uses and filtering by the user's permissions. It then sends one prompt to the LLM: a scope policy, a static platform brief, the Screen Context and the last few Question/Answer pairs. The reply is one structured Answer. It is checked for scope, grounding and PII before the user sees it.

The user sees one of four results:

- **An Answer.** Sanitised Markdown made of Claims, each with citation chips. A Report citation opens the passage, and an engine figure links to its screen. Ungrounded Claims carry an inline "ungrounded" marker. Follow-up questions are offered as clickable suggestions.
- **An Out-of-Scope Refusal.** A fixed message naming what the Assistant can help with. This covers investment advice, market predictions, Clients the user can't see and anything unrelated to the platform.
- **A what-if redirect.** For questions the engine doesn't model, the Answer says so and points to Run Analysis. The Assistant never estimates figures.
- **A failure.** "The Assistant couldn't answer, try again", with a retry button. In replay mode it says "only Suggested Questions work in replay mode".

The Conversation lasts for the login session. It survives reloads and screen changes, and marks each context change with a divider. It ends at logout or expiry. Every turn is kept and anchored in the audit chain, so Compliance Officers and Auditors can review what was asked and what the model saw and said, through the existing LLM Exchanges and Audit screens.

## User Stories

1. As an Advisor, I want to ask a Question about the Portfolio I'm looking at, so that I don't have to piece the answer together from several panels.
2. As an Advisor, I want the Assistant to know which screen and which item I'm on without my describing it, so that "why is this one flagged?" just works.
3. As an Advisor, I want to select a single Trade Line and ask "why this one?", so that the Answer is about that line and not the whole Recommendation.
4. As an Advisor, I want every figure in an Answer to come from the engine, so that I can repeat it to a Client without double-checking.
5. As an Advisor, I want each Claim to show citation chips, so that I can open the Report passage or the screen a figure came from.
6. As an Advisor, I want ungrounded Claims to be marked in place, so that I know which parts to treat with caution.
7. As an Advisor, I want a what-if question to be redirected to Run Analysis, so that I'm never given a made-up projection.
8. As an Advisor, I want to ask follow-up Questions that build on earlier ones, so that I can dig into a complex issue as a conversation.
9. As an Advisor, I want the Conversation to survive a page reload, so that I don't lose my line of questioning.
10. As an Advisor, I want the Conversation to continue when I move from one Portfolio to another, with a visible "context changed" divider, so that I can compare without starting over.
11. As an Advisor, I want each earlier Answer to stay tied to the context it was asked in, so that moving screens doesn't change what earlier Answers meant.
12. As an Advisor, I want clickable follow-up suggestions after an Answer, so that I can explore without wording every Question myself.
13. As an Advisor, I want three Suggested Questions on each screen, so that I learn what the Assistant is good at.
14. As an Advisor, I want a clear refusal when I ask for investment advice or market predictions, so that I know the boundary and the platform stays compliant.
15. As an Advisor, I want Client names shown in the Assistant panel even though the model never sees them, so that Answers read naturally.
16. As a Relationship Manager, I want the Assistant to answer from the data my role can see, so that I can use it without being shown PII my role doesn't hold.
17. As a Relationship Manager, I want questions about a Client outside my permissions to be refused, so that the Assistant can't be used to get around access control.
18. As a Portfolio Manager, I want to ask why one Portfolio is ranked above another on the Queue, so that I understand the priority logic for my book.
19. As a Portfolio Manager, I want the Queue Screen Context to say when it shows only the top 25 rows, so that the Assistant tells me what it couldn't see instead of guessing.
20. As a Portfolio Manager, I want to ask which asset class drives a Portfolio's drift, so that I can prioritise conversations.
21. As a Research Analyst, I want to ask which Insights and Report passages produced a Research Tilt, so that I can check my research was used as intended.
22. As a Research Analyst, I want Report text inside prompts treated as data and not as instructions, so that a malicious or careless Report can't hijack the Assistant.
23. As a Compliance Officer, I want to ask which Suitability Rule produced a warning or breach, so that I can review the exception quickly.
24. As a Compliance Officer, I want to review any user's Assistant turns through the LLM Exchanges screen, so that I can supervise how the Assistant is used.
25. As a Compliance Officer, I want every refusal recorded as an Audit Event, so that attempts to push the Assistant out of scope are visible.
26. As a Compliance Officer, I want the Assistant to be read-only, so that it can never approve, decide or start anything.
27. As an Auditor, I want every Assistant turn anchored in the audit chain through its LLM Exchange, so that chain verification detects tampering with a Conversation.
28. As an Auditor, I want each turn to record a hash of the Screen Context it was asked against, so that I can confirm the context wasn't altered after the fact.
29. As an Auditor, I want failed turns recorded with an `assistant.failed` Audit Event, so that the record has no gaps.
30. As an Auditor, I want to ask the Assistant about the Audit Event or LLM Exchange I'm looking at, so that I can understand complex lineage faster.
31. As an Investment Committee member, I want to ask about the Recommendations awaiting my decision, so that I come to committee prepared.
32. As a Platform Owner, I want to ask how a part of the platform works from the Config or Health screen, so that I can explain the platform without reading code.
33. As a Platform Owner, I want Question length, Questions per Conversation and Questions per user per hour to be config values, so that I can control cost and abuse.
34. As a Platform Owner, I want a plain message when a limit is hit, so that users know why the Assistant stopped answering.
35. As a Platform Owner, I want the Assistant listed on the governance model card with its prompt version, scope policy, limits and latest eval results, so that model governance covers it.
36. As a Platform Owner, I want the Assistant to use the single LLM interface, so that switching model or gateway is still a config change.
37. As any user without `assistant:use`, I want the drawer hidden and the API to refuse me, so that access is controlled centrally.
38. As any user, I want the Assistant in replay mode to answer Suggested Questions and honestly decline others, so that demos work and nothing is faked.
39. As any user, I want a retry button when the Assistant fails, so that a transient error doesn't cost me my Question.
40. As any user, I want the Conversation to end at logout, so that the next person on a shared machine doesn't see it.
41. As any user, I want a "thinking…" state while an Answer is checked, so that I know the Assistant is working even though nothing streams.
42. As a demo presenter, I want Suggested Questions to replay identically against the seeded data, so that a demo is repeatable.
43. As a maintainer, I want an eval set of in-scope, out-of-scope and prompt-injection Questions, so that guardrail regressions are caught before a prompt version bump.

## Implementation Decisions

### Access

- Add a new `assistant:use` permission and grant it to every role in the RBAC matrix. All Assistant endpoints require it. Denials are audited like other permission denials.
- The Screen Context builder enforces the user's other permissions per section. For example, the selected Exchange is included only for users with `llm:read`, and a Portfolio is included only for users with `portfolio:read` who may see that Client. A screen identity naming an entity the user can't read gets the Out-of-Scope Refusal, not an error that reveals whether the entity exists.

### Screen identity and Screen Context

- The screen identity has three parts:
  - a screen kind: queue, portfolio, recommendation, approvals, audit, exchanges, governance, config or health,
  - the entity ids for that screen,
  - an optional selected-item id.

  The server checks that the selected item belongs to the screen's entity before including it.
- There is one **Screen Context builder** per screen kind. Each builder calls the same service functions as that screen's router, so the Assistant sees at most what the screen shows. Contents:
  - **Queue:** the prioritised Portfolios with drift and priority figures.
  - **Portfolio:** Holdings, Target Allocation, Asset-Class Drift and Portfolio Drift, Restrictions, Risk Profile, and the latest Analysis Run summary.
  - **Recommendation:** Trade Lines, Suitability outcomes, Research Tilts, linked Insights with their Report passages, and grounded Claims.
  - **Approvals:** pending items and their status.
  - **Audit:** the selected Audit Events.
  - **Exchanges:** the selected Exchange.
  - **Governance:** the model card.
  - **Config and Health:** only the platform brief.
- **Size budget:** at most 25 rows by the screen's own sort. Report passages are included only for Insights linked to the current Recommendation. When rows are cut, the context carries an explicit note such as "showing 25 of 140". Limits are config values.
- **No PII in prompts:** the Screen Context uses Client ids and pseudonyms only, never names or emails, even for users who hold `client:pii` (ADR-0004). The frontend puts display names back in when rendering.
- **Deterministic serialisation:** the Screen Context is serialised with stable ordering and formatting, so the same screen and data give byte-identical prompts. Suggested Question recordings depend on this.
- **Platform brief:** a short, hand-written explanation of how the platform works, committed alongside the prompts. It is included in every Screen Context and versioned with the Assistant prompt, so editing it requires a prompt version bump.

### Prompt and LLM call

- There is one prompt, `assistant_answer@v1`, kept with the existing prompts. Each Question makes exactly one call through the existing `LlmClient.complete`, and the interface doesn't change.
- The system text holds three things:
  - the scope policy (in scope means the platform's own domain and how it works),
  - the read-only rule,
  - the rule that the Assistant gives no figures beyond those in the Screen Context.
- The user text holds four labelled blocks:
  - the platform brief,
  - the current Screen Context, with Report passages fenced as untrusted data,
  - a history transcript of the last 6 Question/Answer pairs, text only, without earlier Screen Contexts (N is configurable),
  - the new Question.
- **Reply schema:** `in_scope` (boolean), `answer_markdown`, `claims` (each with text and its Report or engine citations, matching the existing Claim citation shape) and `follow_up_questions` (up to 3).
- Capture works as it does today. Every call, whether live, recorded or failed, becomes an LLM Exchange (ADR-0004).

### Checks after the reply

These run in order, and the user sees nothing until they finish. PII runs before grounding, so a rejected Answer is never grounding-checked:

1. **Scope.** If `in_scope` is false, the user gets the fixed Out-of-Scope Refusal and the model's text is discarded.
2. **PII.** If the Answer contains a Client name or email, it is rejected and treated as a failure. This should be impossible given the context, but the check runs anyway.
3. **Grounding.** Claims are validated with the existing grounding logic, against the engine figures in the Screen Context and the Report passages it cites. The current entry point requires a single Client. It needs to accept a figure set that isn't tied to one Client (the Queue) and to link its check to an Assistant turn instead of a Recommendation. Ungrounded Claims stay in the Answer with a flag.

### Conversation and persistence (ADR-0006)

- **A new `conversations` table** holds the user, the login session (the existing server-side session row) and the start and end times. The first Question in a login session creates the Conversation, and logout or session expiry ends it. An ended Conversation can't be resumed.
- **A new append-only `assistant_turns` table** holds the following, and no turn is ever updated or deleted:
  - the Conversation, a sequence number and the Question,
  - the screen identity and the Screen Context hash,
  - the outcome: answered, refused or failed,
  - the Answer JSON, the grounding check id and the Exchange reference.
- **Audit Events:** each turn writes `assistant.answered`, `assistant.refused` or `assistant.failed`, carrying the Exchange reference so chain verification covers it. `assistant.failed` also carries a `reason`: `llm_error` (the call or its capture failed), `unreadable_reply`, `pii` or `replay_miss` (recorded mode had no recording). The turn stores the reason too, so a reload shows the same message. The Exchange is written first, as today.

### API contract

- **Ask:** posting a Question with its screen identity returns the turn: outcome, Answer (Markdown, Claims with their grounding results, follow-up questions), sequence number and Exchange reference.
  - `400` for an over-length Question.
  - `429` when a per-Conversation or per-user-per-hour limit is hit, with a plain message.
  - `403` without `assistant:use`.
- **Read:** the current Conversation returns its turns in order, for rendering after a reload. It returns `204` when there is no Conversation yet.
- **Suggested Questions:** for a screen kind, returns its three Suggested Questions.
- **Retry:** resubmits the same Question and screen identity as a new turn. It is not a separate endpoint.

### Replay mode

- In recorded mode, Suggested Questions replay from committed recordings against the seeded data. Any other Question misses the recording. That turn is stored as failed and the user is told "only Suggested Questions work in replay mode".
- Suggested Questions are defined in code next to each Screen Context builder, three per screen kind. A recording script runs them live against the seeded data, with recording on, and the output is committed like the existing recordings.

### Limits (config, `APP_` prefix)

- Question length at most 2,000 characters.
- At most 50 Questions per Conversation.
- At most 20 Questions per user per hour.
- History window of 6 pairs.
- Screen Context row budget of 25.
- The reply token cap is the model default.

### Frontend

- A collapsible Assistant drawer sits in the app shell. It is shown only when the user holds `assistant:use` and stays open across navigation. Each screen publishes its screen identity and selected item to the drawer.
- The drawer shows:
  - its header (the current context),
  - the turns, with dividers where the context changed,
  - a "thinking…" state,
  - Answers as sanitised Markdown with no raw HTML,
  - citation chips that open the Report passage or go to the figure's source screen,
  - "ungrounded" markers,
  - follow-up suggestions,
  - the Suggested Questions,
  - the refusal, failure, replay-mode and limit messages,
  - a retry button on failures.
- Display names are put back in on the client from data the user is already allowed to see.

### Governance

- The model card lists the Assistant as another LLM use: its prompt version, a scope policy summary, the limits, and the latest live eval results (refusal rate and ungrounded-Claim rate).

## Testing Decisions

- A good test drives the system through the HTTP API, logged in as a role, and asserts only on what a client sees:
  - the turn payload,
  - the Conversation read-back,
  - status codes,
  - Audit Events and LLM Exchanges.

  Tests don't reach into the Screen Context builders, the prompt builder or the guards directly.
- **Seam: the HTTP API**, the same seam as the Queue, LLM Exchange and Run Analysis tests. The LLM is controlled only through the existing `get_llm` dependency override:
  - **Prompt-capturing fake:** returns a scripted reply and records the request it received. It is the only window into what the model saw.
  - **Raising fake:** covers the failure path.
  - **Recorded mode:** committed recordings cover Suggested Questions, and a recording miss covers replay mode.
- Behaviours to cover:
  - an in-scope Question on each screen kind returns an answered turn, and the captured prompt contains that screen's context sections
  - a selected item appears in the prompt; a selected item that doesn't belong to the entity is refused
  - **PII:** an advisor holding `client:pii` asking on a Portfolio screen produces a prompt with no Client name or email
  - **Permissions:** sections the role can't see are absent from the prompt (for example, no Exchange body for roles without `llm:read`); an entity the role can't read gets the Out-of-Scope Refusal and reveals nothing
  - `403` without `assistant:use`, and the denial is audited
  - `in_scope: false` from the model produces the fixed refusal, never the model's text, and an `assistant.refused` Audit Event
  - Claims citing figures absent from the Screen Context come back flagged ungrounded; Claims matching figures and verbatim passages come back grounded
  - an Answer containing a Client name is rejected as a failure
  - Report passages are fenced as untrusted in the prompt; an adversarial Report passage doesn't change the refusal outcome when the model returns out of scope
  - history: after 8 turns, the prompt carries only the last 6 Question/Answer pairs, with no earlier Screen Contexts
  - truncation: a Queue larger than 25 rows produces a prompt with 25 rows and the truncation note
  - Conversation lifecycle: turns persist across requests in the same login, read-back returns them in order, logout ends the Conversation, and a new login starts a fresh one; read-back returns `204` before the first Question
  - each turn writes the right Audit Event with an Exchange reference, and chain verification passes; altering a turn's Exchange breaks verification
  - a raising LLM gives a failed turn, an `assistant.failed` Audit Event and a safe message; retry creates a new turn
  - **Replay mode:** each Suggested Question replays from its recording; a free-form Question gives the replay-mode message
  - limits: an over-length Question gives `400`, and exceeding the per-Conversation or per-hour limits gives `429`
  - the RBAC matrix test includes `assistant:use` for every role
  - the governance model card includes the Assistant entry
- **Eval set:** a committed set of in-scope SME Questions, out-of-scope Questions (advice, predictions, unrelated topics, another Client's id) and prompt-injection Report passages. CI runs the deterministic guards against recorded or scripted replies. A live eval script reports the refusal rate and the ungrounded-Claim rate. It is run manually before a prompt version bump and is not part of CI.
- Prior art:
  - the Queue tests' seeding and `login(role)` fixtures
  - the LLM Exchange API and coverage tests, for Exchange capture and chain anchoring
  - the grounding tests, for Claim validation outcomes
  - the RBAC parametrised denial tests
  - the dependency-override fakes in the Analysis Run tests
  - the recorded-LLM fixture generator, as the model for the Suggested Question recording script
- Frontend: there is no test runner. The drawer is verified by `npm run typecheck` and by new items in the manual E2E checklist:
  - open, close and persist across navigation
  - ask and answer
  - a citation chip opens the passage
  - an ungrounded marker shows
  - a refusal shows
  - the replay-mode message shows
  - retry works
  - the context-change divider appears
  - reload restores the Conversation
  - logout clears it

## Out of Scope

- Any action taken by the Assistant: starting Analysis Runs, deciding or approving Recommendations, drafting Decisions or memos.
- New figures, projections or what-if modelling. The engine owns numbers (ADR-0001).
- Retrieval-augmented generation, vector stores, embeddings, or LLM tool-calling to fetch data. Context is built deterministically by the server.
- Streaming Answers.
- Conversations that resume across logins, conversation search, export, or a dedicated "browse all Conversations" screen.
- A separate classifier call or an external guardrails framework (for example NeMo Guardrails). These are revisited only if the eval shows the in-prompt policy and code checks leak.
- Summarising long histories.
- Multi-language support.
- Redacting PII before persistence for production deployments. ADR-0004 already notes this is needed. It is out of scope here because the Screen Context carries no names or emails.

## Further Notes

- Keeping the `LlmClient` interface unchanged (history goes in as a transcript block in the `user` prompt) is deliberate. Recording, the recording key, Exchange capture and the existing call sites stay untouched, and each Exchange shows exactly what the model saw.
- Suggested Question replays only work if Screen Context serialisation is byte-stable against the seeded data and the fixed market snapshot (ADR-0003). Any change to a builder's output or to the platform brief needs a prompt version bump and re-recording.
- The grounding entry point has to be generalised so it accepts a figure set not tied to one Client and links its check to an Assistant turn. This is the one change to an existing core module.
- This work should start on a fresh branch from `development`, not on `feature/run-analysis-progress`.
