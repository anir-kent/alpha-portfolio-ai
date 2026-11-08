# 3. Context and Scope

The platform's boundary is narrow by design. Humans reach it only through the browser. It calls exactly one external system at run time, the LLM endpoint, and only in live mode. Market data enters through a script an operator runs by hand, never through the running application. Nothing leaves the platform towards a broker, a custodian or a Client.

## 3.1 Business context

C4 Level 1, System Context. What each role expects of the platform is in [1.3 Stakeholders](01-introduction-and-goals.md#13-stakeholders); the table below the diagram adds what crosses the boundary and what stays out of scope.

```mermaid
flowchart TB
  subgraph people["People (one RBAC role each)"]
    direction LR
    advisor["<b>Advisor / Relationship Manager</b><br/>[Person]<br/>Works the Queue, decides Recommendations"]
    analyst["<b>Research Analyst</b><br/>[Person]<br/>Uploads Reports, reviews Insights"]
    approvers["<b>Compliance Officer / Investment Committee</b><br/>[Person]<br/>Decide exceptions and high-impact changes"]
    oversight["<b>Auditor / Portfolio Manager / Platform Owner</b><br/>[Person]<br/>Verify evidence, monitor, configure"]
  end

  platform["<b>Portfolio Rebalancing platform</b><br/>[Software System]<br/>Scores Portfolios, drafts suitability-checked Recommendations,<br/>routes tiered human Decisions, records a hash-chained audit trail.<br/>Never executes trades."]

  llm["<b>LLM endpoint</b><br/>[External System]<br/>OpenAI-compatible chat completions.<br/>Default: OpenRouter, anthropic/claude-sonnet-5.5"]
  twelve["<b>Twelve Data</b><br/>[External System]<br/>Market prices and Instrument metadata (free tier)"]

  advisor -->|"Reviews Queue and drill-down, starts Analysis Runs, accepts / modifies / rejects<br/>[HTTPS, browser]"| platform
  analyst -->|"Uploads Reports, approves / rejects Insights<br/>[HTTPS, browser]"| platform
  approvers -->|"Approve exceptions, block, decide<br/>[HTTPS, browser]"| platform
  oversight -->|"Audit search, chain verification, governance, config, health<br/>[HTTPS, browser]"| platform
  platform -->|"One schema-bound request per pipeline LLM step;<br/>up to the request budget per Assistant Answer<br/>(live mode only; recorded mode replays offline)<br/>[HTTPS, JSON]"| llm
  twelve -.->|"Daily closes into the committed snapshot,<br/>by a manual refresh script, never at run time<br/>[HTTPS, JSON]"| platform

  classDef person fill:#08427b,stroke:#052e56,color:#ffffff
  classDef system fill:#1168bd,stroke:#0b4884,color:#ffffff
  classDef external fill:#999999,stroke:#6b6b6b,color:#ffffff
  class advisor,analyst,approvers,oversight person
  class platform system
  class llm,twelve external
```

[Detailed external interfaces catalog](appendices.md#e7-external-interfaces-catalog).

Outside the boundary altogether: brokers, order management, custody, client communication channels, identity providers and any real client data source.

## 3.2 Technical context

[Detailed external interfaces catalog](appendices.md#e6-external-interfaces-catalog).

The containers behind these channels are in [5.1 Level 1: Containers](05-building-block-view.md#51-level-1-containers).
