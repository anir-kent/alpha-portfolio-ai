# 5. Building Block View

Two zoom levels below the System Context in [3.1 Business context](03-context-and-scope.md#31-business-context). §5.1 opens the platform into its containers (C4 Level 2). §5.2 opens the API process into its components (C4 Level 3) and states the tiered approval policy exactly as the code applies it. §5.3 lists the screens of the React SPA. How the components cooperate at run time is in [6. Runtime View](06-runtime-view.md).

Top-level orientation: the API process is the `app` Python package, with its HTTP endpoints in `app.routers`. The SPA is `frontend/`. The committed data files are under `data/` and `tests/fixtures/llm`.

## 5.1 Level 1: Containers

C4 Level 2, Containers.

```mermaid
flowchart TB
  users["<b>Platform users</b><br/>[Person, one of eight RBAC roles]"]
  operator["<b>Operator</b><br/>[Person]<br/>Runs the seed and refresh scripts"]

  subgraph platform["Portfolio Rebalancing platform"]
    direction TB
    spa["<b>React SPA</b><br/>[Container: React, TypeScript, TanStack Query]<br/>Every screen, gated by the role's permissions.<br/>Typed client generated from the OpenAPI schema"]
    api["<b>API process</b><br/>[Container: Python, FastAPI, one process]<br/>Authentication, RBAC, deterministic engine, LLM steps,<br/>Decisions, audit chain, Assistant"]
    scripts["<b>Operator scripts</b><br/>[Container: Python CLI]<br/>Seed synthetic Clients and research;<br/>refresh the market snapshot"]
    db[("<b>SQLite database</b><br/>[Container: SQLite file]<br/>Users, sessions, config, Clients, Analysis Runs,<br/>Recommendations, Decisions, Reports, Insights,<br/>Audit Events, LLM Exchanges, Conversations")]
    files[("<b>Committed data files</b><br/>[Container: JSON and text files in git]<br/>Market snapshot, fund look-through, seed Reports<br/>and Insights, LLM recordings, latest live eval")]
  end

  llm["<b>LLM endpoint</b><br/>[External System]<br/>OpenAI-compatible chat completions"]
  twelve["<b>Twelve Data</b><br/>[External System]"]

  users -->|"Uses<br/>[HTTPS, browser]"| spa
  spa -->|"JSON under /api; SSE for Run Step progress<br/>and the LLM Exchange feed<br/>[HTTP, session cookie]"| api
  api -->|"Reads and writes<br/>[SQLAlchemy]"| db
  api -->|"Reads the snapshot and look-through;<br/>replays the configured recordings in recorded mode<br/>[files]"| files
  api -->|"One schema-bound request per pipeline step;<br/>a bounded Trajectory per Answer, live mode only<br/>[HTTPS, JSON]"| llm
  operator -->|"Runs by hand<br/>[shell]"| scripts
  scripts -->|"Seeds<br/>[SQLAlchemy]"| db
  scripts -->|"Reads seeds; writes the refreshed snapshot<br/>[files]"| files
  scripts -->|"Daily closes and metadata, manual refresh only<br/>[HTTPS, JSON]"| twelve

  classDef person fill:#08427b,stroke:#052e56,color:#ffffff
  classDef container fill:#438dd5,stroke:#2e6295,color:#ffffff
  classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
  class users,operator person
  class spa,api,scripts,db,files container
  class llm,twelve external
```

[Detailed container entry points](appendices.md#e10-container-entry-points).

## 5.2 Level 2: API process components

The deterministic engine computes Drift, Priority, Trade Lines and Suitability. Analysis Runs coordinate scoring and narrative steps; Recommendations and the approvals policy enforce human Decisions. Research owns Report ingestion and approved Insights. Grounding checks structured Claims. The Assistant reuses permission-filtered screen builders for read-only lookups. LLM capture and the audit chain retain evidence; governance derives quality views. Config, market data, health and Auth/RBAC provide shared services. The catalog below names each module and HTTP entry point.

C4 Level 3, Components of the API process. Every component persists through the SQLAlchemy models of the one SQLite database; those edges are left out to keep the picture readable. Every HTTP endpoint passes through Auth / RBAC first; only the dependencies that carry a design decision are drawn.

```mermaid
flowchart TB
  spa["<b>React SPA</b><br/>[Container]"]

  subgraph api["API process"]
    direction TB
    auth["<b>Auth / RBAC</b><br/>Sessions, role-permission matrix,<br/>server-side enforcement"]

    subgraph work["Analysis and Decisions"]
      direction TB
      runs["<b>Analysis Runs</b><br/>Background run, Run Steps,<br/>SSE progress"]
      engine["<b>Deterministic engine</b><br/>Drift, priority, opportunity,<br/>rebalance, suitability"]
      recs["<b>Recommendations and Decisions</b><br/>Draft, version, decide, supersede"]
      policy["<b>Approvals policy</b><br/>Required steps and next status"]
    end

    subgraph ai["AI under deterministic control"]
      direction TB
      research["<b>Research and Insights</b><br/>Report ingestion, Insight Review,<br/>approved-only retrieval"]
      aisteps["<b>AI-on-Recommendations steps</b><br/>Research Tilt, Recommendation and<br/>priority narratives, AI step summary"]
      grounding["<b>Grounding validator</b><br/>Every Claim cited and checked"]
      assistant["<b>Assistant</b><br/>Bounded read-only agent: lookups,<br/>self-correction, request budget;<br/>Screen Context"]
    end

    subgraph evidence["Evidence"]
      direction TB
      capture["<b>LLM client and Exchange capture</b><br/>pydantic-ai live / replay Models,<br/>fail-closed capture, Trajectories, Exchange feed"]
      audit["<b>Audit chain</b><br/>Single write path, hash chain,<br/>lineage, verify"]
      governance["<b>Governance</b><br/>AI quality, prompt log, model card,<br/>adversarial fixtures"]
    end

    subgraph platformsvc["Shared services"]
      direction LR
      config["<b>Config</b><br/>Validated business config"]
      market["<b>Market data</b><br/>Snapshot and universe"]
      health["<b>Health</b><br/>Liveness and readiness"]
    end
  end

  llm["<b>LLM endpoint</b><br/>[External System]"]
  files[("<b>Committed data files</b>")]

  spa -->|"/api, session cookie"| auth
  auth -->|"access denied"| audit
  runs -->|"scores"| engine
  runs -->|"proposes tilt, writes narratives"| aisteps
  runs -->|"drafts, supersedes"| recs
  recs -->|"re-evaluates modifications"| engine
  recs -->|"plan, next status"| policy
  recs -->|"applies the bounded tilt"| aisteps
  policy -->|"thresholds"| config
  engine -->|"bands, weights, limits"| config
  engine -->|"prices, look-through"| market
  aisteps -->|"approved Insights only"| research
  aisteps -->|"checks Claims"| grounding
  aisteps -->|"one schema-bound call per step"| capture
  research -->|"extracts Insights"| capture
  grounding -->|"verbatim passage on page"| research
  assistant -->|"checks Claims"| grounding
  assistant -->|"a bounded Trajectory per Question"| capture
  assistant -->|"Screen Context and lookups through the<br/>screens' own read services"| recs
  capture -->|"live mode"| llm
  capture -->|"recorded mode"| files
  market -->|"reads"| files
  audit -->|"verify recomputes<br/>Exchange hashes"| capture
  recs -->|"Decisions, versions"| audit
  research -->|"extraction, Insight Review"| audit
  governance -->|"prompt / version log"| audit
  governance -->|"adversarial fixtures"| grounding

  classDef component fill:#85bbf0,stroke:#5d82a8,color:#000000
  classDef container fill:#438dd5,stroke:#2e6295,color:#ffffff
  classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
  class auth,runs,engine,recs,policy,research,aisteps,grounding,assistant,capture,audit,governance,config,market,health component
  class spa,files container
  class llm external
```

[Detailed component entry points and responsibilities](appendices.md#e9-component-entry-points-and-responsibilities).

Process settings (secrets, LLM mode and endpoint, Assistant limits, file locations) are read from `APP_`-prefixed environment variables by one settings object; they are not part of the business config above.

### Tiered approval policy

Advisor approval is always required (`recommendation:decide`). Compliance follows only for a post-trade Suitability breach (`compliance:decide`); warnings alone do not require it. Investment Committee follows when turnover or any single Trade Line is **at or above** the configured percentage threshold (`committee:decide`). Approved executes nothing.

The plan is recomputed at every read and Decision. Lower thresholds can add a future Committee step; raising a threshold does not remove a step already waiting. Wrong-step Decisions receive 409; missing permissions receive 403 with an `access_denied` event. A modification creates a new version back at Advisor; a newer Analysis Run supersedes open Recommendations. Decisions and rationale are audited.

[Detailed tiered approval policy](appendices.md#e33-tiered-approval-policy). The sequence is in [6.2](06-runtime-view.md#62-tiered-decisions).

## 5.3 React SPA screens

Each screen appears only for a role holding the permission in brackets; the server checks it again on every call. Every screen except Research publishes a screen identity for the Assistant drawer, never its data; the server builds the Screen Context from that identity.

[Detailed spa screen catalog](appendices.md#e8-spa-screen-catalog).
