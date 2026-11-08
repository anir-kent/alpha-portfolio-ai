# Appendices

## Appendix A: AI Governance

This appendix records the controls and evidence available to Model Risk reviewers. It describes which concerns the platform **addresses / maps to**; it makes no regulatory assurance claim. The system is a demonstrator using synthetic Clients and a committed market snapshot. Production acceptance remains with the firm's reviewers, including assessment of the deterministic engine itself.

### Engine and LLM boundary

The deterministic engine owns every valuation, Drift, priority score, Trade Line and Suitability verdict. The LLM extracts Insights, proposes Research Tilts that code bounds, and explains engine facts with citations. It cannot execute trades or record Decisions. A failed AI step leaves the engine result intact; the AI contribution is unavailable or falls back as described in [8.1](08-crosscutting-concepts.md#81-deterministic-engine-ownership).

The four pipeline tasks each make one schema-bound request. The current Assistant is a bounded, read-only agent with permission-checked lookups and at most one grounding self-correction, under [ADR-0010](../adr/0010-assistant-is-a-bounded-read-only-agent-on-pydantic-ai.md). This supersedes the single-call Assistant assumed by the original architecture ticket. Its authoritative limits and prompt versions are generated in [8.10](08-crosscutting-concepts.md#810-assistant-usage-limits) and [8.3](08-crosscutting-concepts.md#83-llm-call-shape-and-prompt-versioning).

### Guardrails and their limits

| Guardrail | Where it acts | What happens when it fires / limit of the control |
| --- | --- | --- |
| Grounding | [Grounding validator](../../app/grounding.py), on Report citations and engine figures in Claims; extraction also verifies taxonomy and passage-on-page | Invalid Claims receive issue codes and Audit Events. Memo and Queue prose is assembled from grounded Claims. The Assistant may correct once; remaining ungrounded Claims stay visible and flagged. This checks structured Claims, not the truth of every sentence in free-form Markdown. |
| Research Tilt bound | [Research Tilt assessment](../../app/research_tilt.py), before the rebalancer | Unknown Insight ids and direction-conflicting proposals are dropped; aggregated subject tilts are clipped to `tilt_bound_pp` (default 2 pp). Asset-Class target shifts are scaled to keep the bound. The engine computes all resulting Trade Lines. |
| Approved-Insights-only | [Report service](../../app/reports.py), `approved_insights`, used by research consumers | Pending and rejected Insights cannot influence a Research Tilt. A Research Analyst must approve an extracted Insight first; approval and rejection are audited. |
| Fenced Report passages | [Screen Context builders](../../app/screen_context.py) and [Assistant prompt](../../app/prompts.py) | Assistant passages and selected Exchange text are JSON strings in explicit `<<<…>>>` fences; the system prompt tells the model to treat them as data. Injection attempts still pass through scope, schema and Grounding checks. Fencing is an instruction boundary, not a deterministic injection detector. Extraction pages and pipeline tilt passages have no equivalent fences. |
| Out-of-Scope Refusal | [Assistant](../../app/assistant.py), after the model's `in_scope` decision | An out-of-scope reply is discarded; only the platform's fixed refusal is stored as the Answer and shown, with `assistant.refused`. Advice, predictions and unrelated topics are excluded. Scope classification remains model-dependent. |
| Permission-filtered Screen Context | [Screen Context builders](../../app/screen_context.py) for initial context and every read-only lookup | An unreadable initial screen is refused before any model call. A forbidden or absent lookup returns the same "not found or not permitted for your role" result. Client ids replace names and emails even for roles holding `client:pii`. |
| PII check on replies | [Assistant output review](../../app/assistant.py), before an Answer is persisted or displayed | A case-insensitive match to any stored Client's full name or email discards the Answer and records a failed turn (`pii`), without coaching a retry. This is an exact-value backstop, not general PII detection; raw model Exchanges are still retained with restricted access. |
| Usage limits | [Assistant](../../app/assistant.py) and [agent request budget](../../app/assistant_agent.py) | Overlong Questions receive 400; per-Conversation and rolling user-hour limits receive 429. Context/history are bounded. Exhausting the request budget fails the turn (`budget_exhausted`). See the generated defaults in [8.10](08-crosscutting-concepts.md#810-assistant-usage-limits); these are request/turn limits, not token-cost budgets. |
| Fail-closed Exchange capture | [Captured model interface](../../app/pydantic_llm.py) and [Exchange store](../../app/exchanges.py) | Each request, replayed or live, must be stored before its result is consumed; a capture failure fails the call. Audit Events anchor the ordered Exchanges by id and hash. Verification detects missing or changed anchored Exchanges; it has no external immutable anchor ([R-09](11-risks-and-technical-debt.md#r-09)). |

Human control adds a separate gate: Advisor approval always; Compliance on a Suitability breach; Investment Committee when configured turnover or single-Trade-Line thresholds are crossed. The plan is recalculated when thresholds change. See [tiered approval policy](05-building-block-view.md#tiered-approval-policy) and [audit recording](08-crosscutting-concepts.md#82-audit-recording).

## Appendix B: Model inventory and evaluation

### Model inventory

| Inventory field | As implemented |
| --- | --- |
| Model of record | `anthropic/claude-sonnet-5.5` |
| Provider interface | OpenRouter by default, `https://openrouter.ai/api/v1/`, through an OpenAI-compatible endpoint |
| Sampling | `APP_LLM_TEMPERATURE` is unset by default, so temperature is omitted from requests; it is optional for models that accept it |
| Substitution | `APP_LLM_MODEL` and `APP_LLM_BASE_URL` select the model/endpoint; switching requires new evaluation evidence and recordings, not an assumption that this model's results transfer |
| Evidence per call | Task, model, prompt version, mode, prompt, parsed result/error and Trajectory position in each Exchange; hash references in its Audit Event. Wire messages, raw reply and usage are present where available; pipeline replays have no wire capture. |
| Operating modes | Recorded replay is the default, with no provider call; live mode requires the API key. See [8.4](08-crosscutting-concepts.md#84-recorded-and-live-llm-modes). |

The inventory below is checked against [the prompt registry](../../app/prompts.py). The [generated prompt table](08-crosscutting-concepts.md#83-llm-call-shape-and-prompt-versioning) is the code-derived authority when a prompt changes.

| Task | Prompt version | Permitted model contribution |
| --- | --- | --- |
| Report Insight extraction | `insight_extraction@v1` | Propose subject, direction, confidence and verbatim page evidence; starts pending review |
| Research Tilt | `research_tilt@v1` | Propose pp per supplied approved Insight; code validates and bounds it |
| Recommendation memo | `recommendation_narrative@v1` | Explain the engine's Recommendation through cited Claims |
| Queue narrative | `priority_narrative@v1` | Explain priority through cited Claims; cannot re-score or rank Clients |
| Assistant Answer and platform brief | `assistant_answer@v5` | Explain platform/screen/lookup data; read-only tools, bounded requests, one possible self-correction |

### Evaluation method

The [eval set and HTTP runner](../../tests/fixtures/assistant_eval.py) use seeded synthetic Portfolios, planted Report passages and one fresh Conversation per case. Its categories are `in_scope`, `platform`, `advice`, `prediction`, `unrelated`, `other_client`, `injection`, `cross_screen`, `self_correction` and `not_permitted`. Current cases exercise permission-filtered lookups and the bounded agent as well as the original scope/grounding controls.

CI runs `uv run pytest tests/test_assistant_eval.py` against a scripted model. It checks deterministic refusals, PII rejection, invented figures being flagged, fencing, lookup permission denial, canary leakage detection and the self-correction limit. Scripted CI demonstrates the guards, not the live model's behaviour. The [PII and Assistant tests](../../tests/test_assistant.py), [research tests](../../tests/test_research.py) and [Exchange coverage tests](../../tests/test_llm_exchange_coverage.py) provide complementary evidence.

For a manual live run, activate `.venv` and run `uv run python -m tests.fixtures.assistant_eval` with the model-of-record endpoint and key configured in the environment or git-ignored `.env`. Only Assistant calls go live; setup Analysis Run steps replay recordings. The runner writes `data/assistant_eval.json`; no live run is performed by this documentation change. Check its model and prompt version before accepting results for a release.

Metrics follow the runner: refusal rate is refusals divided by expected-refusal cases that reached the model; false-refusal rate is refusals divided by expected-answer cases; ungrounded-Claim rate is flagged Claims divided by all Claims in displayed Answers. Failed turns count failed outcomes. `injection_leaks` counts injection-category cases that fail their expectations, including canary detection. A case can pass while retaining flagged Claims, so the pass count is not a factual-accuracy score.

### Live evidence on the model of record

Both runs below used **`anthropic/claude-sonnet-5.5`**. The ticket's historical result is quoted from `data/assistant_eval.json` at commit `a6802bd4ad92cd4ce81911daf32de5cbbe9e59e7` (inspect with `git show a6802bd4ad92cd4ce81911daf32de5cbbe9e59e7:data/assistant_eval.json`). The latest result is quoted from the [current eval results file](../../data/assistant_eval.json).

| Evidence | Ticket baseline (historical) | Current bounded Assistant |
| --- | --- | --- |
| Prompt | `assistant_answer@v3` | `assistant_answer@v5` |
| Run date (UTC) | `2026-11-07T14:03:14+00:00` | `2026-11-08T08:57:45+00:00` |
| Passed / cases | **30/30** | **33/33** |
| Refusal rate | 1.0 | 1.0 |
| False-refusal rate | 0.0 | 0.0 |
| Claims total | 23 | 36 |
| Ungrounded-Claim rate | 0.17391304347826086 (4/23) | 0.0 (0/36) |
| Failed turns | 0 | 0 |
| Injection leaks | 0 | 0 |

These are finite synthetic-case observations, not production safety estimates. The v3 result does not validate v5's tool loop, and the changed case set prevents a like-for-like improvement claim. No result from another model is used here. Independent validation, wider adversarial/data coverage, repeated runs and operational monitoring remain production review work ([§11](11-risks-and-technical-debt.md), [Roadmap](13-roadmap.md)).

## Appendix C: Framework mapping

These tables map implemented controls to review concerns; they do not establish completeness, independent validation or organizational adoption. Evidence links point to the implementation described above and the body sections.

### SR 11-7 (primary mapping requested by the architecture spec)

The mapping uses the historical [SR 11-7 guidance, sections IV–VI](https://www.federalreserve.gov/boarddocs/srletters/2011/sr1107a1.pdf). **Framework currency:** [SR 26-2, issued 17 April 2026](https://www.federalreserve.gov/supervisionreg/srletters/sr2602.htm), supersedes SR 11-7. This table preserves the spec's review vocabulary; Model Risk must determine the applicable current guidance and refresh the mapping before production approval.

| Review concern | Controls that address it | Evidence / remaining work |
| --- | --- | --- |
| IV: Development, implementation and use | Defined task inventory, versioned schemas/prompts, engine ownership, bounded Research Tilts and read-only Assistant | [Appendix A](#appendix-a-ai-governance), [inventory](#model-inventory), [8.1–8.4](08-crosscutting-concepts.md#81-deterministic-engine-ownership). Provider internals/training are not validated here; production data and use limits need review. |
| V: Conceptual soundness | Explicit engine/LLM boundary, constrained inputs/outputs and documented architecture decisions | [§9 decisions](09-architecture-decisions.md). An independent assessment of engine assumptions, Suitability Rules and model limitations remains outstanding. |
| V: Ongoing monitoring | Stored Grounding verdicts, prompt/version log, capture-health and adversarial fixtures on the governance panel | [Governance implementation](../../app/governance.py). No scheduled independent review, drift alerts or operational telemetry; see [§11](11-risks-and-technical-debt.md). |
| V: Outcomes analysis | Scripted guard tests plus dated live model-of-record eval, with refusal and ungrounded-Claim metrics | [Evaluation method and results](#evaluation-method). Synthetic finite cases do not provide portfolio outcome backtesting or independent model validation. |
| VI: Governance, policies and controls | Role separation, human Insight Review, tiered Decisions, generated permission matrix, audit/Exchange lineage and documented owner/reviewer fields | [8.8 matrix](08-crosscutting-concepts.md#88-authentication-and-authorization), [document control](index.md#document-control). Reviewer fields remain TBD; formal model approval, change policy and external audit anchoring remain open. |

### NIST AI RMF (secondary mapping)

This mapping uses the four functions in [NIST AI RMF 1.0](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf), a voluntary risk-management framework.

| Function | Controls that address it | Limits / evidence |
| --- | --- | --- |
| Govern | Document ownership, prompt inventory, role-separated Decisions and audit lineage | [Index](index.md#document-control), [8.2](08-crosscutting-concepts.md#82-audit-recording). Firm policy, risk acceptance and reviewer sign-off are not implemented by these artifacts. |
| Map | Defined advisory purpose, synthetic data, prohibited execution/advice, engine and provider boundaries | [Scope](03-context-and-scope.md), [Appendix A](#appendix-a-ai-governance). Production stakeholders, data and harms need reassessment. |
| Measure | Grounding checks, adversarial fixtures, scripted tests and dated live eval metrics | [Appendix B](#appendix-b-model-inventory-and-evaluation). No broad fairness, repeated-run robustness or real-data outcome assessment is evidenced. |
| Manage | Bound/clipped tilts, rejected PII replies, permission-filtered lookups, request budgets, failed-step degradation and human approvals | [Guardrails](#guardrails-and-their-limits), [§11](11-risks-and-technical-debt.md). Incident response, provider terms and production monitoring remain deployment work. |

### EU AI Act classification note

Our preliminary classification inference is that this synthetic-data, internal portfolio advisory demonstrator is outside the listed high-risk use cases: it does not assess creditworthiness, price life/health insurance or execute trades. Human approval alone does not determine classification. The relevant legal tests are Article 6 and Annexes I/III; financial-sector use by itself is insufficient. The Assistant also needs assessment against Article 50's interaction-transparency provisions. [Regulation (EU) 2024/1689](https://eur-lex.europa.eu/eli/reg/2024/1689/oj/eng)

Before any EU production deployment, legal review must confirm territorial scope, intended purpose, provider/deployer roles, applicable dates and current amendments. A change to credit scoring, insurance or another listed purpose requires reclassification; this architecture note is not a legal determination.

## Appendix D: Security and threat summary

### Authentication and authorization

[Authentication](../../app/routers/auth.py) uses [scrypt password hashing](../../app/security.py) with a random 16-byte salt and constant-time digest comparison. Login issues an opaque random token in an `HttpOnly`, `SameSite=Lax`, path `/` cookie; only its SHA-256 digest is stored server-side. Sessions expire after `APP_SESSION_TTL_HOURS` (12 by default); expiry deletes the session when next seen and ends its Conversation. Logout deletes the server session, ends the Conversation and clears the cookie. `Secure` follows `APP_COOKIE_SECURE`, off by default.

Authorization is enforced on the server through [permission dependencies](../../app/deps.py) and Assistant context/lookup builders. A missing session produces 401. An authenticated role lacking an endpoint permission receives 403, and `access_denied` records the actor, required permission, HTTP method and path. Assistant lookups use a non-disclosing unavailable result rather than the endpoint's 403 path. UI hiding is cosmetic. The [generated role × permission matrix](08-crosscutting-concepts.md#88-authentication-and-authorization) is the review authority; `client:pii` belongs only to Advisor and Compliance Officer.

### Secrets and sensitive data

Settings read `APP_*` environment variables or the git-ignored `.env`. The committed [.env.example](../../.env.example) contains an obvious password placeholder and empty API keys; operators supply their own values. The LLM key is sent only in the Authorization header, which capture excludes. Raw provider reply/error text redacts the configured LLM key, but parsed content and request messages are not generically scrubbed: a secret echoed into parsed content or entered as user text can persist. Credential configuration is not intentionally stored in Exchanges. These are sensitive records with `llm:read` access restricted by the generated matrix.

Prompts and Screen Contexts identify Clients by pseudonymous ids, never stored names/emails, even for an Advisor. [8.9](08-crosscutting-concepts.md#89-pii-stance) links the guarding tests. This does not sanitize arbitrary user-entered Questions or uploaded Reports: those can contain sensitive text, leave for the provider in live mode and remain in Exchanges. The full-name/email reply backstop is limited to stored Client values. Provider data-processing terms, retention and a real-data protection review remain prerequisites ([R-07](11-risks-and-technical-debt.md#r-07), [R-08](11-risks-and-technical-debt.md#r-08)).

### Prompt injection and residual threats

Report text and Questions enter user messages, never system instructions. The Assistant fences Report passages, selected Exchange text and lookup content as untrusted data; schema validation, Grounding, permission filtering, read-only tools and request budgets contain the resulting actions. Extraction uses plain page text and Research Tilt uses JSON passages, so the Assistant's explicit fencing must not be read as pipeline-wide protection. A malicious passage can still distort an extracted view or persuade a model inside its allowed schema; human Insight Review and deterministic tilt limits reduce the impact. A model can also misclassify scope or emit unsupported free-form prose. The live canary result is evidence for tested attacks only.

The authoritative gaps and mitigations are in [§11 Risks and Technical Debt](11-risks-and-technical-debt.md) and the [Target / Production Roadmap](13-roadmap.md): no SSO/MFA or login throttling, no CSRF token, `Secure` off by default, local SQLite without database encryption/access separation, no external audit anchor and no structured operational monitoring. Hash verification detects alterations relative to the stored chain; a privileged database writer can rewrite the entire chain. These controls address demonstrator risks and require the listed production work before go-live.
