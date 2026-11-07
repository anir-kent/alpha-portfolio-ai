# 3. Context and Scope

## 3.1 Business context

_To be written in architecture-document ticket 04._ Placeholder System Context until then:

```mermaid
flowchart LR
  users["Advisors, Compliance, Investment Committee,<br/>Research Analysts, Auditors, Platform Owner"]
  platform["Portfolio Rebalancing platform"]
  llm["LLM endpoint<br/>(OpenAI-compatible)"]
  market["Market data provider"]
  users -->|review and decide| platform
  platform -->|schema-bound calls| llm
  market -->|snapshot| platform
```

## 3.2 Technical context

_To be written in architecture-document ticket 04._
