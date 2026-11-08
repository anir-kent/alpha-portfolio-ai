Status: ready-for-agent

# pydantic-ai LLM layer, and an agentic Assistant with an auditable LLM Trajectory

Vocabulary follows `GLOSSARY.md` (new term: **LLM Trajectory**). Decisions respect `docs/adr/0001`, `0002`, `0004` (as amended), `0006`, `0008`, `0009` and the new `0010-assistant-is-a-bounded-read-only-agent-on-pydantic-ai`, which supersedes `0007`.

## Problem Statement

The platform's LLM layer is a hand-written OpenAI-compatible HTTP client. Every step, including the Assistant, is one fixed prompt and one reply. The Assistant can therefore answer only from the Screen Context of the screen the user is on. Suppose an Advisor on the Queue asks "why is portfolio 12 flagged, and is there an approved Insight on its largest sector?" The Assistant cannot look at portfolio 12 or the Insights. It either refuses or answers from partial context. The platform also cannot show agentic patterns at all: tool use, a bounded reasoning loop, self-correction against a guardrail, least-privilege tool access, and an auditable record of a multi-step model trajectory. Showing those patterns is a goal of this demonstrator, and showing them without giving up the glass box (every model call captured verbatim and anchored in the hash chain) is the point. Today, adding any of this would mean growing the hand-written client into a home-made agent framework.

## Solution

The LLM layer moves to pydantic-ai in two stages.

**Stage 1 changes no behaviour.** All five LLM steps run on pydantic-ai through the same step-facing call they use today. The four pipeline steps (Insight extraction, Research Tilt proposal, Recommendation narrative, priority narrative) stay single schema-bound calls with native structured output, no tools and no retries. Capture keeps ADR-0004's promise: live calls are captured byte-for-byte at the HTTP transport, and replays and test models are captured at the model boundary. Each Audit Event now anchors an ordered list of LLM Exchanges, its LLM Trajectory, which for these steps is a list of one. Recorded mode replays each model request from a key over the full request, and all recordings are regenerated once. The hand-written client is deleted.

**Stage 2 makes the Assistant an agent.** Its first prompt is unchanged: the Screen Context plus the Conversation so far. It can then call read-only tools that look up other screens (the Queue, a Portfolio, a Recommendation, Approvals, the Audit log, Governance) and list approved Insights. Every tool sees exactly what the asking user could see on that screen and nothing else. Lookups that aren't permitted come back as "not permitted for your role", and the Answer has to say so. Before an Answer is accepted, it is checked:
- A PII leak rejects it outright.
- Ungrounded Claims trigger one self-correction attempt that names what was wrong.
- An Answer may use at most six model requests.

Every model request is an LLM Exchange in the turn's Trajectory, anchored in the turn's Audit Event. Every user of the Assistant sees a **"How I answered"** expander on each Answer: the lookups made with their arguments, a short result summary, any self-correction, the requests used against the budget, and tokens. Holders of `llm:read` see the same Trajectory as an ordered group on the LLM Exchanges page and in its drawer.

## User Stories

### Advisor and other Assistant users

1. As an Advisor, I want to ask the Assistant about a Portfolio that isn't on my current screen, so that I don't have to navigate away to get an answer.
2. As an Advisor on the Queue, I want the Assistant to look up a Portfolio's detail when I ask why it is ranked where it is, so that the answer reflects its actual Holdings and drift.
3. As an Advisor, I want the Assistant to look up a Recommendation's Trade Lines and Suitability results when I ask about them, so that I get the engine's figures, not a guess.
4. As an Advisor, I want the Assistant to find approved Insights for a sector I ask about, so that I can see whether research supports a tilt.
5. As an Advisor, I want an Answer that combines several lookups, so that a question spanning two screens gets one coherent reply.
6. As an Advisor, I want every number in an Answer to come from a figure the engine computed, whether on my screen or in a lookup, so that I can trust the numbers.
7. As an Advisor, I want Claims that cite figures from a lookup to be checked for grounding just like Claims citing my screen, so that a lookup isn't a loophole.
8. As an Advisor, I want the Assistant to correct itself once when its first draft contains ungrounded Claims, so that I more often get a fully grounded Answer.
9. As an Advisor, I want any Claim still ungrounded after self-correction to be shown flagged, as today, so that nothing unchecked passes as fact.
10. As an Advisor, I want a "How I answered" expander on each Answer, so that I can see which lookups the Assistant made.
11. As an Advisor, I want each step in "How I answered" to show the lookup's name, its arguments and a short result summary, so that I can follow the reasoning without reading raw prompts.
12. As an Advisor, I want "How I answered" to show when the Assistant corrected itself and why, so that I understand why the Answer changed.
13. As an Advisor, I want to see how many model requests an Answer used out of its budget, and the tokens, so that the cost of an Answer is visible.
14. As an Advisor, I want a single-step Answer to show a one-step "How I answered", so that the view is consistent whether or not lookups happened.
15. As an Advisor, I want the Assistant to tell me plainly when a lookup was not permitted for my role, so that I know the gap is about access, not data.
16. As an Advisor, I want a lookup for an entity that doesn't exist and one I can't see to get the same reply, so that the Assistant never reveals whether something exists.
17. As an Advisor, I want an Answer that would expose a Client's name or email to be rejected outright, so that PII never reaches me through the Assistant.
18. As an Advisor, I want an Answer that ran out of its request budget to fail with a clear message, so that I know to ask a narrower Question.
19. As an Advisor, I want Out-of-Scope Refusals to behave exactly as today, so that the Assistant still declines general investment advice and predictions.
20. As an Advisor, I want each new Question to get a fresh set of lookups, so that an Answer never relies on stale data looked up for an earlier Question.
21. As an Advisor, I want the Conversation history to carry on working as today, so that follow-up Questions still have their context.
22. As an Advisor, I want Suggested Questions to keep working in recorded mode, including those whose Answers use lookups, so that demos work with no network.
23. As an Advisor, I want a recorded-mode miss on a free-form Question to say that only Suggested Questions work in replay mode, as today, so that the failure is understandable.
24. As a Research Analyst, I want the Assistant's Insight lookup to return only approved Insights, so that unreviewed Insights never leak into Answers.
25. As a Compliance Officer using the Assistant, I want lookups on screens my role can see, such as Approvals, to work for me, so that the Assistant is useful in my role too.
26. As a user without audit access, I want an audit lookup to come back not permitted, so that the Assistant respects the same boundaries as the screens.
27. As any user, I want the Assistant never to change anything (no Decisions, no Insight Reviews, no configuration), so that it stays a read-only helper.

### Auditor and holders of `llm:read`

28. As an Auditor, I want every model request in an Answer captured as its own LLM Exchange, so that I can read everything the model saw and said across the whole Trajectory.
29. As an Auditor, I want each live Exchange to store the exact request and response bytes that crossed the wire, so that capture doesn't depend on how a framework re-describes them.
30. As an Auditor, I want each Exchange to record its Trajectory and its position in it, so that I can rebuild the order of steps.
31. As an Auditor, I want an Exchange's Trajectory and position covered by its content hash, so that reordering Exchanges is detected.
32. As an Auditor, I want each Assistant turn's Audit Event to anchor the ordered list of its Exchanges by id and hash, so that the whole Trajectory is tamper-evident.
33. As an Auditor, I want chain verification to recompute every Exchange in every anchored Trajectory and report the first mismatch, missing row or order break, so that I know exactly where trust breaks.
34. As an Auditor, I want Audit Events written before this change, with their single Exchange reference, to keep verifying, so that the existing chain stays valid.
35. As an Auditor, I want the LLM Exchanges page to group an Answer's Exchanges as one Trajectory in order, so that I review a multi-step Answer as one unit.
36. As an Auditor, I want the Exchange drawer to show the Trajectory the Exchange belongs to and let me step to its neighbours, so that I can walk the Trajectory.
37. As an Auditor, I want the tool calls and tool results the model saw to be visible verbatim inside the next Exchange's request, so that no lookup result is hidden from review.
38. As an Auditor, I want a self-correction attempt to appear as its own Exchange, with the guardrail feedback sent to the model visible in it, so that I can see what the model was told was wrong.
39. As an Auditor, I want a failed model request (transport error, unreadable reply) inside a Trajectory captured as an error Exchange and the turn failed with its reason, so that failures stay visible.
40. As an Auditor, I want a budget-exhausted turn to keep every Exchange it made, anchored in its `assistant.failed` event, so that a runaway Trajectory is fully reviewable.
41. As an Auditor, I want replayed Exchanges labelled recorded, as today, so that a demo replay is never mistaken for a live call.
42. As an Auditor, I want the four pipeline steps to still produce exactly one Exchange each, so that their audit story hasn't changed.
43. As an Auditor, I want the grounding verdict of the final Answer linked as today, and a rejected first draft's issues visible through its retry Exchange, so that both drafts can be reviewed.
44. As an Auditor, I want provider SDK retries switched off, so that no model call happens that isn't captured.

### Platform owner

45. As a platform owner, I want the OpenRouter attribution title and the "require every parameter" routing preference still sent on live calls, so that schema enforcement and attribution survive the move.
46. As a platform owner, I want switching the base URL to another OpenAI-compatible gateway to still be a configuration change, so that the platform stays gateway-ready.
47. As a platform owner, I want the API key never stored in an Exchange, so that credentials stay out of the glass box.
48. As a platform owner, I want the Assistant's request budget to be configurable, defaulting to six, so that I can tune cost against capability.
49. As a platform owner, I want the Governance page's capture health to count Trajectories as well as Exchanges, so that I can see capture working for agentic turns.
50. As a platform owner, I want recorded mode to stay the default, with no network, so that tests and demos are deterministic.
51. As a platform owner, I want a changed prompt, schema, tool definition or tool result to miss its recording rather than replay a stale reply, so that replays never lie.
52. As a platform owner, I want one command to regenerate all committed recordings, so that the one-time format change and future prompt changes are routine.

### Developer and reviewer

53. As a developer, I want the four pipeline steps to keep calling the same step-facing interface, so that their code and prompts don't change in Stage 1.
54. As a developer, I want every test to fake the LLM at one seam, the pydantic-ai model, so that the capture path runs under every test.
55. As a developer, I want a helper that scripts a multi-step Trajectory (tool calls, then a final reply) for a test, so that agentic behaviour is easy to test.
56. As a developer, I want a guard that fails when any Assistant tool is a plain function rather than a coroutine, so that a tool can never run off the caller's thread and break session-bound capture.
57. As a developer, I want Report upload to work when the LLM layer runs its own event loop, so that the async upload route doesn't break.
58. As a developer, I want the architecture document updated to reflect ADR-0010 and its check to pass, so that the docs don't contradict the code.
59. As an interviewer watching a demo, I want to ask a cross-screen Question and see the lookups, the self-correction and the budget in "How I answered", so that the agentic patterns and their guardrails are obvious.

## Implementation Decisions

### Staging
- **Stage 1** moves all five steps onto pydantic-ai, with new capture, anchoring and replay, and no change in behaviour. It deletes the hand-written OpenAI-compatible client. **Stage 2** adds the Assistant's tools, self-correction, budget and the Trajectory UI. Stage 1 must be complete before Stage 2 starts.

### LLM layer module
- The step-facing interface stays: a step builds one LLM request (task, prompt version, system text, user prompt, reply JSON schema) and calls `complete` once. It becomes a thin adapter that runs a single-call pydantic-ai Agent over an injected pydantic-ai **Model**: native structured output over the request's JSON schema (pydantic-ai's structured-dict output; check the exact name against the pinned version), no tools, zero output retries. The reply is still validated by the step's own Pydantic model as today.
- The injected Model is the **only test seam**. `build_llm` (and the FastAPI dependency) produces the live Model, the replay Model, or a test-supplied Model, always wrapped in capture.
- **Live Model**: pydantic-ai's OpenAI-compatible chat model through its OpenRouter provider when the base URL is OpenRouter, and the generic OpenAI-compatible provider otherwise. It must send the attribution title and, for OpenRouter only, `provider: {require_parameters: true}` (through the provider's routing settings or the extra request body). SDK `max_retries` is 0. Temperature behaves as today (left out when unset). The provider is given a custom `httpx` client (legacy `httpx`, not `httpx2`) whose transport records each request and response.
- **Dependency**: `pydantic-ai-slim` with the OpenAI and OpenRouter extras, added with `uv add`. No Logfire.

### Capture (ADR-0004 as amended)
- Capture wraps the Model (a pydantic-ai wrapper model). It writes one LLM Exchange per model request, as soon as the reply or error is known, before the caller writes its Audit Event. This keeps the existing session binding and savepoint behaviour inside an Analysis Run.
- For live calls, the Exchange's request messages and raw reply are the bytes the recording transport saw for that request. Replay and test Models record the request fields and the recorded or scripted reply, labelled `recorded` (replay) as today.
- **Schema change (hand-written, idempotent migration, ADR-0008):** LLM Exchanges gain `trajectory_id` and `trajectory_position`. Both are part of the content hash. Earlier rows have neither and are treated as single-Exchange Trajectories.
- **Audit anchoring**: an Audit Event carries an ordered `exchanges` list of `{exchange_id, exchange_hash}`. The existing helper that builds an event's Exchange reference returns this list from a response, an error or a Trajectory result. Events with the old single `exchange_id`/`exchange_hash` stay valid.
- **Verification** walks each anchored list. It recomputes each Exchange's hash, checks that the Exchanges share one `trajectory_id` with positions 0..n-1 in list order, and reports the first mismatch, missing row or order break against the Audit Event. Events with no reference are pre-capture, as today.
- Exchange outcome stays transport-level only. A reply later rejected by a validator stays `ok`.

### Replay
- A replay Model answers each model request from a recording keyed by a hash of: task, prompt version, reply schema, tool definitions (names, descriptions, parameter schemas) and the full message list sent so far, including earlier tool calls and tool results. A miss raises the existing recording-missing error, never a guess.
- Live mode with a record directory writes one recording per model request, in the format the replay Model reads.
- All committed recordings are regenerated: the fixture regeneration commands, the Suggested Question recordings and the assistant eval recordings. The old format isn't read.

### Assistant agent
- The Assistant is a pydantic-ai Agent with `deps` holding the asking user, the database session, market data and settings. It runs through `run_sync` from the existing synchronous `ask` path. Its first user message keeps today's structure: the Screen Context block, the Conversation history block (Question and Answer pairs only, last N, ADR-0006) and the Question. A Suggested Question is still sent without history.
- **Tools** are all `async def`, read-only, and implemented over the existing Screen Context builders so they inherit permission checks and the PII-free shape:
  - `look_up_queue(filters?)`
  - `look_up_portfolio(portfolio_id)`
  - `look_up_recommendation(recommendation_id)`
  - `look_up_approvals()`
  - `look_up_audit(filters?)`
  - `look_up_governance()`
  - `list_approved_insights(sector?)`, a new read over Insights with approved Insight Review status.

  The exchanges screen isn't exposed. Each tool returns the builder's serialised, fenced context, the same format as the Screen Context block. When a builder returns nothing, or the id doesn't exist, the tool returns the same plain result: "not found or not permitted for your role". That is never an error and never a retry. Tool argument validation errors are reported back to the model by pydantic-ai, with the tool retry budget at 0.
- **Figures**: every figure in a tool result's `figures` joins the turn's citable figure set, alongside the Screen Context's. Grounding validates Claims against that union.
- **Output validator**: on each candidate reply it runs the existing PII check, then grounding.
  - A PII hit ends the run, and the turn fails with reason `pii` (no retry).
  - Ungrounded Claims raise `ModelRetry` with a message listing each failing Claim and its issue. The output retry budget is 1.
  - On the final attempt, ungrounded Claims are accepted and flagged as today. Only the final Answer's grounding check is stored as the turn's `grounding_check_id`. The rejected draft's issues live in the retry Exchange.
- **Budget**: `UsageLimits(request_limit=N)` with N from settings, default 6. Token limits are off. Exceeding it fails the turn with the new reason `budget_exhausted` and a user-facing message suggesting a narrower Question. Every Exchange made so far is anchored in `assistant.failed`.
- A failure inside the Trajectory fails the turn with the existing reasons (`llm_error`, `unreadable_reply`, `replay_miss`). This includes a transport error, an unreadable reply or a replay miss on any request.
- Out-of-Scope Refusal and the existing pre-model refusal path (an unreadable or non-existent screen entity writes `assistant.refused` with no model call) are unchanged.
- The Assistant prompt version is bumped. Its system text explains the tools, that every figure must come from the Screen Context or a lookup, and that "not permitted" must be reported honestly.

### Assistant turn API and UI
- A turn gains a `trajectory` summary, built server-side from the Trajectory and visible to anyone who can see the turn:
  - an ordered list of steps: model request, tool call (name, arguments, one-line result summary such as "portfolio 12: 14 holdings, drift 6.2 pp" or "not permitted"), or self-correction (the issue count)
  - `requests_used` and `request_limit`
  - input and output tokens

  It contains no raw prompt or reply text. The OpenAPI schema and generated frontend types are regenerated.
- The Assistant drawer shows a collapsed "How I answered" expander per Answer that renders this summary.
- The LLM Exchanges list groups rows by `trajectory_id` (a Trajectory of one looks like today's row). The drawer shows "step k of n" with previous and next navigation. Still `llm:read` only.
- Governance capture health adds a Trajectory count and the share of Assistant turns that used tools.

### Execution model
- All agent runs use `run_sync`. A guard (test) fails if any registered Assistant tool function is not a coroutine function.
- The async Report upload route reads the upload asynchronously, then runs ingestion (which calls the LLM) in the threadpool, so `run_sync` never runs inside the server's event loop.

### Documentation
- ADR-0010 is written, ADR-0007 is marked superseded and ADR-0004 is marked amended (done with this spec). The architecture document sections that describe "one call per step / no agent loop" (constraints, solution strategy, building blocks, runtime view, crosscutting concepts, ADR index) are updated to ADR-0010, with an Assistant Trajectory added to the runtime view. The architecture document check passes. `GLOSSARY.md` has **LLM Trajectory** (done).

## Testing Decisions

- **What makes a good test here:** drive public behaviour, meaning the HTTP routes, `ask`, an Analysis Run and Report upload. Substitute only the pydantic-ai Model, and assert on what users and Auditors can observe: the response body, the turn's `trajectory` summary, Exchange rows through the LLM Exchanges API, Audit Event payloads and the chain verification result. Don't assert on pydantic-ai internals, message-part classes or private helpers.
- **One substitution seam:** the pydantic-ai Model. The existing test doubles that stub `complete` (the stub, blocking, narrative-failing, prompt-capturing, suggested-question and assistant-eval fakes) are rewritten as scripted Models, built on pydantic-ai's function model behind a small project helper that scripts a sequence of replies and tool calls and records the requests it received. `ALLOW_MODEL_REQUESTS` is off in the test suite.
- **Live wire capture** is tested on its own against `httpx.MockTransport`, following the existing OpenAI-compatible client tests in the research tests. These tests check:
  - the request bytes and raw reply are stored verbatim
  - the attribution title is sent, and `require_parameters` is sent for OpenRouter only
  - no API key appears in the Exchange
  - one failing HTTP response produces exactly one request (SDK retries off) and one error Exchange
- **Capture and chain:** extend the LLM Exchange tests and chain tamper tests. Cover a Trajectory of one and of several, tampering with one Exchange in a Trajectory, swapping positions, deleting a middle Exchange, and legacy single-reference events still verifying.
- **Replay:** a recorded Trajectory replays identically. Changing a tool result, a tool definition or the schema misses. A miss on a later request in a Trajectory fails the turn with `replay_miss`.
- **Assistant agentic behaviour** (extend the Assistant tests):
  - a scripted cross-screen Trajectory produces an Answer whose Claims cite tool-result figures and are grounded
  - a forbidden lookup returns "not found or not permitted" and is the same for a non-existent id
  - an ungrounded first draft triggers exactly one retry carrying the issue list, and a second ungrounded draft is kept and flagged
  - PII in a reply fails with `pii` and no retry
  - a seventh request fails with `budget_exhausted`, with all six Exchanges anchored
  - history carries only Question and Answer pairs
  - Suggested Questions replay with no network
- **Per role:** extend the RBAC and PII prompt-guard tests so that every tool, for every role, never returns a Client name or email and returns "not permitted" exactly where the matching screen would be forbidden.
- **Execution guard:** a test that every Assistant tool is a coroutine function. A test that Report upload through the async route succeeds with a scripted Model.
- **Pipeline steps:** the existing Analysis Run, research, narrative and priority narrative tests keep passing with scripted Models. Each still produces one Exchange per step, anchored as a list of one.
- **Assistant eval** (prior art: the assistant eval fixture and test) is re-recorded and gains at least one multi-step case.
- **Frontend:** the "How I answered" expander and the grouped Exchanges list follow the existing component tests for the Assistant drawer and Exchange drawer, if present. Otherwise they're covered by the manual E2E checklist.
- **Prior art:** the LLM Exchange, coverage and API tests, the Assistant and Suggested Question tests, the Analysis Run tests, the research tests (transport-mocked client), the audit tamper tests, and the architecture document test.

## Out of Scope

- Live streaming of tool steps to the browser.
- Multi-agent designs, delegation, or a planner and worker split.
- Any write, action or side-effecting tool. The Assistant stays read-only.
- Agentic behaviour (tools, retries, self-correction) for Insight extraction, Research Tilt proposal or the two narrative steps.
- Retrieval over a vector store or embeddings.
- Logfire or OpenTelemetry instrumentation.
- `httpx2`.
- Carrying earlier turns' tool calls or results into later turns.
- Token or cost limits beyond the request cap.
- Redacting Exchanges before persistence (still a production concern, per ADR-0004).

## Further Notes

- The main motivation is to show agentic AI patterns convincingly in a regulated, auditable setting, for example to an interviewer. The demo script is a cross-screen Question asked from the Queue, then "How I answered" showing the lookups, a self-correction and the budget, then the same Trajectory on the LLM Exchanges page, then chain verification. The rejected options in ADR-0010 are the talking points for "why not multi-agent / LangGraph / write tools".
- pydantic-ai v2.66.0 was current when this was written (2026-11-08). Before relying on the exact names (structured-dict output, the OpenRouter routing setting, the wrapper model's request methods), check them against the pinned version with Context7.
- The LLM provider remains OpenRouter with the configured Anthropic model. Recordings are keyed to it.
