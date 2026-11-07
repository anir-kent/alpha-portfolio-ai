Status: ready-for-agent

# Architecture Document: an arc42 + C4 baseline for ARB sign-off that stays true to the code

Vocabulary follows `GLOSSARY.md` (Client, Portfolio, Holding, Instrument, Drift, Tolerance Band, Analysis Run, Run Step, Priority, Suitability Rule, Trade Line, Recommendation, Decision, Report, Insight, Research Tilt, Grounding, Audit Event, LLM Exchange, Assistant, Conversation, Question, Answer, Screen Context). This spec introduces no new domain terms: everything below is about the document, not the domain. Decisions respect `docs/adr/0001` to `0006` and add ADR-0007 and ADR-0008 (below).

## Problem Statement

The platform is built and merged on `development`: deterministic engine, Research and Insights with Grounding, tiered human approvals, hash-chained audit, the LLM glass box, the Assistant and the Research Analyst UI. The architecture knowledge is spread across six ADRs, a glossary, specs, scratch tickets, a README and the code itself.

An Architecture Review Board, model risk / compliance reviewers and InfoSec cannot sign off on that. They need one structured, versioned document that:

- explains what the system is, its boundaries and its quality goals;
- shows the structure at several zoom levels and the key runtime flows;
- states honestly what exists today and what is still roadmap;
- maps the AI controls to the model-risk frameworks they work under;
- lists the known risks and gaps rather than leaving reviewers to find them.

Business sponsors and GTM audiences need a short, visual version of the same story: AI proposes, the engine decides, humans approve, everything is audited.

A hand-written document like this goes stale within weeks. Facts such as the RBAC matrix, prompt versions and config defaults drift silently from the code, and a stale architecture document is worse than none in a regulated review.

## Solution

A **living architecture document**:

- Markdown in an architecture folder under `docs/`, one file per arc42 section, Mermaid diagrams inline.
- A lean body of 15–20 pages, with depth pushed into linked ADRs, specs and appendices.
- A 2-page **Executive Summary** with one Excalidraw value-flow overview for sponsors and GTM.
- A **Target / Production Roadmap** section, clearly separated from the as-is sections.
- An **AI Governance appendix** mapping controls to SR 11-7 (primary), NIST AI RMF (secondary) and an EU AI Act classification note. It uses "addresses", never "certifies".

Code-derived facts are **generated from code** into marked regions of the document, so they cannot drift. A single document build command has two modes:

- **check**, which runs in CI. It fails on a missing section, a broken diagram, a broken link or a stale generated region.
- **build**, which runs per release. It produces a frozen PDF with a cover stamped with version, commit SHA and date, plus a document-control block.

## User Stories

### ARB / enterprise architects
1. As an ARB reviewer, I want the document to follow arc42's 12 sections, so that I can find any concern in the place I expect it.
2. As an ARB reviewer, I want a C4 System Context diagram showing the platform, its human roles and its external systems (the LLM endpoint and the market data provider), so that I understand the boundary in one picture.
3. As an ARB reviewer, I want a C4 Container diagram, so that I see the React SPA, the FastAPI API process, the SQLite store, the committed data files and the LLM endpoint, and how they talk to each other.
4. As an ARB reviewer, I want C4 Component diagrams for the API process, so that I see these components and their dependencies:
   - deterministic engine
   - research and Insights
   - AI-on-Recommendations steps
   - Recommendations and Decisions
   - approvals policy
   - Grounding validator
   - audit chain
   - LLM Exchange capture
   - Assistant
   - governance
   - config
   - health
   - auth / RBAC
5. As an ARB reviewer, I want runtime sequence diagrams for an Analysis Run, tiered approval, Report ingestion to Insight approval, and an Assistant Question, so that I can follow the critical flows end to end.
6. As an ARB reviewer, I want the quality goals ranked (Auditability, Explainability, Human control / safety, Data protection, Reproducibility), with concrete quality scenarios, so that I can judge the design against stated goals.
7. As an ARB reviewer, I want performance and scalability named as explicit non-goals for the current version, so that I don't mistake their absence for an oversight.
8. As an ARB reviewer, I want constraints stated up front, so that I understand the solution space: never executes trades; synthetic Clients; a committed market data snapshot; a single process.
9. As an ARB reviewer, I want the solution strategy to summarise the few decisions that shape everything, with each linked to its ADR, so that I can drill down only where I care.
10. As an ARB reviewer, I want section 9 to link to the ADRs rather than restate them, so that there is one source of truth per decision.
11. As an ARB reviewer, I want an ADR explaining why LLM steps are single, schema-bound calls with no agent framework, agent loop or RAG, so that the deliberate choice is not read as immaturity.
12. As an ARB reviewer, I want an ADR explaining the single-process, single-SQLite-file design with hand-written idempotent migrations, so that I understand the current-scope trade-off and where the roadmap lifts it.
13. As an ARB reviewer, I want a cloud-agnostic logical deployment view plus one reference mapping to Azure, so that I can judge a concrete production path without the design being locked to one cloud. The mapping covers App Service or AKS, Azure Database for PostgreSQL, Entra ID, Key Vault and the LLM behind a LiteLLM gateway.
14. As an ARB reviewer, I want the as-is sections to describe only what the code on the baseline commit does, so that I never approve aspirational design as built.
15. As an ARB reviewer, I want the roadmap in its own section with each item tied to the risk or non-goal it addresses, so that I can see why each step exists.
16. As an ARB reviewer, I want a risks and technical debt section, so that I can see the known gaps with their mitigations. The gaps are:
    - no SSO or MFA
    - no CSRF token
    - `Secure` cookie off by default
    - a single process
    - SQLite
    - in-process Run Step progress
    - no structured logging, metrics or tracing
    - no frontend test runner
    - synthetic data

### Model risk and compliance
17. As a model risk reviewer, I want a model inventory, so that I know exactly what model risk I am assessing:
    - the model of record, `anthropic/claude-sonnet-5.5` via OpenRouter, behind an OpenAI-compatible interface
    - temperature omitted by default (Claude 5 models accept none; it is an optional setting)
    - each prompt and its version
    - each task the LLM performs
18. As a model risk reviewer, I want the boundary between the deterministic engine and the LLM stated precisely, so that I can confirm no number, trade or suitability verdict comes from the model. The engine owns every number, trade and suitability verdict. The LLM only extracts, proposes bounded tilts and explains with citations.
19. As a model risk reviewer, I want every guardrail listed with where it acts and what happens when it fires, so that I can assess control coverage. The guardrails are:
    - Grounding
    - the Research Tilt bound
    - approved-Insights-only
    - fenced untrusted Report passages
    - Out-of-Scope Refusal
    - permission-filtered Screen Context
    - PII check on replies
    - usage limits
    - fail-closed Exchange capture
20. As a model risk reviewer, I want the eval set described (cases by category, metrics, how CI runs it against a scripted model, how live runs happen) with the latest live results on the model of record, so that I can see measured behaviour. The appendix quotes the live run on the model of record (30/30, `assistant_answer@v3`) and must never quote results from another model.
21. As a model risk reviewer, I want the controls mapped to SR 11-7 (development, validation, governance) and NIST AI RMF (Govern / Map / Measure / Manage), so that I can file the review in my own framework.
22. As a model risk reviewer, I want a short EU AI Act classification note, so that I know how the use case is positioned.
23. As a compliance reviewer, I want the tiered approval policy described exactly as the code applies it, so that I can confirm segregation of duties:
    - Advisor always;
    - Compliance only on a Suitability breach;
    - Investment Committee only when turnover or a single Trade Line crosses configured thresholds;
    - re-planning when thresholds change.
24. As a compliance reviewer, I want the audit chain explained (single write path, hash chaining, lineage links, verify endpoint, tamper test) and how LLM Exchanges and Assistant turns are anchored in it, so that I can rely on it as evidence.
25. As a compliance reviewer, I want the PII stance explained, so that I can confirm Client data does not leave the platform in prompts:
    - pseudonyms only in prompts and Screen Contexts;
    - `client:pii` held only by advisor and compliance_officer;
    - the test that guards this.
26. As a compliance reviewer, I want the document to say it describes which framework controls the system addresses, not that the system is certified, so that the document makes no claim the firm cannot stand behind.

### InfoSec
27. As an InfoSec reviewer, I want authentication described, so that I can assess session security:
    - scrypt password hashing;
    - an opaque token in an HttpOnly, SameSite=Lax cookie;
    - only the token's SHA-256 stored server-side;
    - TTL;
    - logout behaviour.
28. As an InfoSec reviewer, I want the RBAC role × permission matrix in the document, generated from code, so that I can review least privilege against the real matrix and not a stale copy.
29. As an InfoSec reviewer, I want to know that authorization is enforced server-side only and that denials write an Audit Event, so that I can trust the UI hiding is cosmetic only.
30. As an InfoSec reviewer, I want secrets handling described (environment variables, git-ignored env file, API key only in the Authorization header and redacted from errors, credentials never stored in Exchanges), so that I can assess credential exposure.
31. As an InfoSec reviewer, I want the prompt-injection defences described for Report passages and Assistant Questions, so that I can assess the LLM attack surface.
32. As an InfoSec reviewer, I want the known security gaps listed in Risks with roadmap mitigations, so that I review a plan, not a surprise.
33. As an InfoSec reviewer, I want the committed example environment file to contain no realistic credential, so that the repository passes a basic secrets review.

### Engineering
34. As an engineer joining the team, I want the building-block view to name each component's responsibility and its entry point at the right altitude, so that I can navigate the codebase.
35. As an engineer, I want the crosscutting concepts collected in one section, so that I apply them consistently:
    - deterministic engine ownership
    - audit recording
    - LLM call shape and prompt versioning
    - recorded / live LLM modes
    - SSE streaming
    - config service
    - idempotent migrations
36. As an engineer, I want the document check to run in CI, so that a PR that changes the RBAC matrix, a prompt version, an Audit Event type, a config default or a usage limit fails until the document is regenerated.
37. As an engineer, I want one command that regenerates the code-derived regions, so that keeping the document current costs seconds.
38. As an engineer, I want broken Mermaid diagrams and broken relative links to fail the check, so that the published document never ships a broken picture or dead link.
39. As an engineer, I want the testing approach documented (API-seam integration tests, pure-engine tests, recorded LLM fixtures, eval set, manual e2e), so that I know how quality is assured.

### Sponsors, GTM and the document owner
40. As a business sponsor, I want a 2-page Executive Summary with the business problem, the value, the "AI proposes, engine decides, humans approve, everything audited" principle, and the roadmap headline, so that I can grasp the solution without reading the body.
41. As a GTM lead, I want one hand-drawn-style Excalidraw value-flow diagram, so that I can show the story in one slide. The flow runs Report → approved Insights → deterministic engine → grounded narrative → tiered human approval, with the audit chain underneath.
42. As the document owner, I want a cover and document-control block, so that the document has formal ownership and traceability:
    - owner: Aniruddh Kendurkar, Principal AI/Data Architect;
    - status: Draft / Under ARB Review / Approved;
    - TBD reviewer fields for the ARB chair, Model Risk and InfoSec;
    - a version history with one row per export.
43. As the document owner, I want a per-release PDF stamped with version, commit SHA and date, so that the ARB signs against an exact, uneditable baseline.
44. As the document owner, I want the document to stay living (updated in the same PR as architectural changes), so that the next review starts from a current baseline, not a rewrite.
45. As the document owner, I want a fresh-context ARB-reviewer pass against an arc42 checklist before the first export, so that gaps are found by me, not by the board.

## Implementation Decisions

### Baseline
- As-is content describes `development` after demo-polish ticket 15 of ai-portfolio-rebalancing is committed. Both the Assistant and Research Analyst UI branches are already merged there.
- The work happens on a `docs/architecture-document` branch cut from that commit. The commit SHA of each export goes on its PDF cover.

### Document structure
- One Markdown file per arc42 section (01 to 12), plus:
  - an Executive Summary;
  - a Roadmap (Target / Production);
  - appendices: AI Governance, model inventory and eval, framework mapping, and security / threat summary.
- An index file orders the sections and holds the document-control block.
- §12 Glossary links to `GLOSSARY.md`. It does not copy it.
- §9 Decisions links to `docs/adr/`. It does not restate the ADRs.
- Quality goals, in order: Auditability, Explainability, Human control / safety, Data protection, Reproducibility. Each gets at least one quality scenario in §10. Performance and scalability are named non-goals and covered by the Roadmap.

### Diagrams
- Mermaid, inline:
  - C4 L1 System Context;
  - C4 L2 Containers;
  - C4 L3 Components for the API process;
  - sequences for Analysis Run with Run Step SSE, tiered approval, Report ingestion → Insight approval → Grounding, and an Assistant Question with guardrails;
  - logical deployment and Azure reference deployment.
- One Excalidraw value-flow overview for the Executive Summary, committed as both source and exported image.

### New ADRs (written before the sections that link to them)
- **ADR-0007 — LLM steps are single, schema-bound calls.** No agent framework, no agent loop, no RAG; a plain OpenAI-compatible HTTP client.
  - Alternatives considered: LangChain / LangGraph orchestration; tool-calling agent loops; retrieval over a vector store.
  - Chosen for: auditability (one call, one Exchange, one Audit Event), determinism under replay, and small attack surface.
  - Consequence: richer multi-step reasoning is a deliberate future decision, not a drift.
- **ADR-0008 — one API process on one SQLite file, hand-written idempotent migrations.**
  - Alternatives considered: PostgreSQL plus Alembic from day one.
  - Chosen for: zero-ops local demo and an atomic scoring transaction.
  - Consequence: single-process assumptions (ADR-0005 Run Step registry, serialised audit writes). The Roadmap lifts these via PostgreSQL and an external progress store.

### Code-derived regions
- Marked regions in the Markdown are delimited by begin/end markers naming a generator. A generator renders one table from the live code modules:
  - RBAC role × permission matrix (from the role-permission matrix);
  - prompt names and versions (from the prompt registry);
  - Audit Event types (from the audit module's event type list);
  - config defaults (from the config service defaults);
  - Assistant usage limits (from the Assistant's limits).
- Generators import the application modules directly. They never parse source text. Content outside markers is never touched.

### Document build command (the one seam)
- A single Python entry point under `scripts/`, run with `uv`. It has three modes.
- **check** fails, with a precise message per problem, on any of:
  - a missing section file or required heading;
  - a Mermaid block that fails to render;
  - a broken relative link or anchor, including ADR, glossary-term and spec links;
  - a stale code-derived region.
- **regenerate** rewrites the code-derived regions in place.
- **build**:
  1. pre-renders Mermaid to SVG with mermaid-cli via `npx`;
  2. assembles HTML in index order with an embedded stylesheet;
  3. stamps the cover with version, commit SHA and date;
  4. prints the PDF through headless Chromium (Puppeteer bundled with mermaid-cli).
- Build refuses to run on a dirty working tree, so the stamped SHA is truthful.
- No pandoc and no WeasyPrint, so no new system dependency. Any Python dependency is added with `uv add`.
- CI runs check in the job that already has Node available.

### Model of record and eval
- The document names the settings default, `anthropic/claude-sonnet-5.5` through OpenRouter (any OpenAI-compatible endpoint, e.g. a LiteLLM gateway), as the model of record, and states that the model is swappable behind the interface.
- The live eval has already been re-run on the model of record (ai-portfolio-rebalancing ticket 15: 30/30, `assistant_answer@v3`, 2026-11-07). The AI Governance appendix quotes the live eval results file, and only while it reports the model of record; the eval ticket is a guard, not a pending step.

### Housekeeping
- The committed example environment file's sample password (still present after ticket 15) is replaced with an obvious placeholder.

### Excluded wording
- The AI Governance appendix says "addresses" or "maps to", never "compliant with" or "certified".

## Testing Decisions

- **What makes a good test:** it drives the document build command's check and regenerate modes from the outside, and asserts on outcomes: exit status and reported problems. It never asserts on the internals of the generators or the link checker.
- **Module under test:** the document build command only (one seam). Test cases:
  - check passes on the real document;
  - check reports a stale region after a generator's source changes (simulated with a temporary document copy whose marked region is edited);
  - check reports a broken relative link;
  - check reports a missing required section;
  - regenerate makes a stale document pass check;
  - regenerate leaves content outside markers byte-identical.
- Mermaid rendering is exercised in check. Tests that need Node are skipped with a clear reason when `npx` is unavailable.
- Build (PDF) is not run in CI. It is verified manually per release by opening the PDF and confirming the cover stamp and diagrams.
- **Prior art:**
  - `scripts/export_openapi.py`, a code artifact turned into a consumed file;
  - the HTTP-seam pytest style and `tmp_path` isolation in `tests/conftest.py`;
  - the guard-style tests in `tests/test_llm_exchange_coverage.py`, which fail when code and an invariant diverge.
- **Not tested automatically:** prose accuracy and completeness, and Excalidraw content. These are covered by a fresh-context ARB-reviewer subagent pass against an arc42 checklist, recorded as a comment on the review ticket.

## Out of Scope

- Fixing the security gaps themselves (SSO/MFA, CSRF, Secure-cookie defaults), PostgreSQL migration, containerisation, IaC, observability tooling. They are documented as Risks and Roadmap items only. The exception is the sample-password placeholder.
- Re-running the live eval (already done on the model of record; any future re-run is the user's step with their own key).
- Claiming regulatory compliance or certification.
- Mapping to clouds other than Azure.
- DOCX export, Confluence / Notion publication, or a hosted documentation site.
- Changes to `GLOSSARY.md`: no new domain terms are introduced.
- Restating ADR content inside the document.

## Further Notes

- Primary readers are ARB architects and model risk / compliance. Secondary readers are InfoSec, engineering and sponsors. Write to ARB rigour, and let the Executive Summary carry the GTM story.
- Natural parallelism once the skeleton and build command exist: ADRs, diagrams and section drafts are independent of each other. The live eval on the model of record is already done, so the AI Governance appendix is not blocked on it.
- Suggested installed skills while working the tickets:
  - `documentation-and-adrs` for ADR-0007/0008;
  - `architecture-blueprint-generator` for first drafts of §5 and §8, always edited against the code;
  - `excalidraw-diagram` for the overview.
