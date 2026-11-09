# 6. Runtime View

Four flows carry the platform's critical behaviour. Each diagram shows two kinds of evidence: where Audit Events are appended to the chain (the **Audit chain** lane) and where LLM Exchanges are stored (the **LLM Exchanges** lane). Both are tables in the one SQLite file ([ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md)). They get their own lanes because they are the record an Auditor relies on.

Some rules hold in all four flows:

- **One appended event, one commit.** Every Audit Event is appended under a process-wide lock and committed on its own ([ADR-0002](../adr/0002-hash-chained-append-only-audit-log.md)). Business rows flushed before that event commit with it.
- **The LLM Exchange comes first.** Every model request goes through one capturing wrapper. The wrapper stores the LLM Exchange, for a reply or an error, before the caller writes the Audit Event that references it by id and hash. If the LLM Exchange cannot be stored, the request fails ([ADR-0004](../adr/0004-llm-exchanges-stored-separately-anchored-in-audit-chain.md)).
- **One call per pipeline step, a bounded Trajectory per Answer.** Insight extraction, the Research Tilt and both narratives are each a single, schema-bound request with no tools. Only an Assistant Answer may take several model requests: read-only lookups and at most one self-correction, within the request budget. Either way the step's one Audit Event anchors its whole LLM Trajectory, in order ([ADR-0010](../adr/0010-assistant-is-a-bounded-read-only-agent-on-pydantic-ai.md)).
- **Replay misses fail.** In recorded mode a prompt with no recording raises a replay miss. It is never answered with a guess, and it fails the call like any other LLM error.
- **Denials are audited.** A role that lacks the endpoint's permission gets `403`, and an `access_denied` Audit Event is written. The diagrams leave this out.

The components named in the lanes are described in [5.2 Level 2: API process components](05-building-block-view.md#52-level-2-api-process-components). Domain terms are defined in [`GLOSSARY.md`](../../GLOSSARY.md).

## 6.1 Analysis Run

An Advisor or Relationship Manager (`analysis:run`) starts an Analysis Run. The run executes on a background thread, and its Run Step progress streams to the browser over server-sent events. Only one run is in flight per process ([ADR-0005](../adr/0005-run-step-progress-in-process.md)).

```mermaid
sequenceDiagram
  autonumber
  actor U as Advisor / Relationship Manager
  participant SPA as React SPA
  participant API as API: analysis router
  participant R as AnalysisRuns + ProgressRegistry<br/>(process memory)
  participant W as Run thread<br/>(run_analysis)
  participant DB as SQLite: business rows
  participant LLM as ModelLlm (capture) → live<br/>or replay Model
  participant EX as LLM Exchanges
  participant AU as Audit chain

  U->>SPA: Run Analysis
  SPA->>API: POST /api/analysis/runs
  API->>R: start() under the start lock
  alt a run is already in flight
    R-->>API: that run's snapshot, not started
    API-->>SPA: 409 with the in-flight run's snapshot
    Note over SPA: The modal attaches to the other run's progress
  else no run in flight
    R->>DB: insert the run row (no outcome yet), commit
    R->>R: publish snapshot seq 1, every Run Step pending
    R-)W: start a daemon thread with its own DB session
    API-->>SPA: 202 with the snapshot
  end

  SPA->>API: GET /api/analysis/runs/{id}/events (EventSource)
  Note over API,R: Each poll interval: read the registry and push the full snapshot<br/>as event "progress" (id = seq) only when seq changed. Keepalive otherwise.<br/>After the stream's maximum duration the browser reconnects with Last-Event-ID.

  Note over W,EX: Phase 1: one write transaction (Load inputs, Score Portfolios)
  W->>DB: load config, targets, Restrictions, Clients, approved Insights, open Recommendations
  loop each Portfolio
    W->>W: drift, Suitability Rules, priority score (deterministic engine)
    opt LLM configured, Portfolio outside its Tolerance Band, approved Insights exist
      W->>LLM: Research Tilt proposal (session-bound)
      LLM->>EX: store Exchange under a savepoint (reply or error)
      LLM-->>W: proposal with Exchange id and hash, or LlmError (no tilt)
      W->>W: engine bounds the proposed tilt
    end
    W->>DB: flush priority and suitability results, and, when the plan has Trade Lines,<br/>Recommendation v1 (pending_advisor) with its tilt record
    W->>R: portfolios_scored(done, total)
  end

  Note over W,AU: Phase 2: Record run, one commit per Audit Event
  W->>AU: analysis_run_started (this commit makes the scoring rows durable)
  W->>AU: recommendation_superseded for each open Recommendation it replaces
  loop each Portfolio
    W->>AU: suitability_evaluated, priority_scored
    opt a Recommendation was drafted
      W->>AU: research_tilt_proposed (+ research_tilt_applied), carrying the Exchange ref
      W->>AU: recommendation_drafted, then suitability_evaluated (post-trade)
    end
  end
  W->>DB: Phase 3: run.completed = true, commit (now the current run)

  Note over W,AU: AI steps: each failure only marks its Run Step failed
  loop each Portfolio with relevant approved Insights
    W->>LLM: priority narrative
    LLM->>EX: store Exchange (own DB session, commit)
    LLM-->>W: reply with Exchange id and hash, or LlmError
    W->>AU: grounding_checked (+ claim_ungrounded per flagged Claim)
    W->>DB: priority narrative row (complete or failed), commit
    W->>AU: priority_narrative_generated, carrying the Exchange ref
  end
  loop each of the run's Recommendations with a Research Tilt record
    W->>LLM: Recommendation narrative (memo)
    LLM->>EX: store Exchange (own DB session, commit)
    LLM-->>W: reply with Exchange id and hash, or LlmError
    W->>AU: grounding_checked (+ claim_ungrounded)
    W->>DB: memo row (complete or failed), commit
    W->>AU: memo_generated, carrying the Exchange ref
  end

  W->>DB: save outcome and Run Step results on the run row, commit
  W->>R: publish the final snapshot (the run leaves flight)
  API-->>SPA: final "progress" event, stream closes
  SPA->>SPA: refresh the Queue and Portfolio views
```

[Detailed 6.1 analysis run controls and failure paths](appendices.md#e18-61-analysis-run-controls-and-failure-paths).

## 6.2 Tiered Decisions

Every Recommendation starts at `pending_advisor`. The approvals policy decides which further steps it needs:

```mermaid
sequenceDiagram
  autonumber
  actor A as Advisor / Relationship Manager
  actor CO as Compliance Officer
  actor IC as Investment Committee
  participant API as API: recommendations router
  participant P as Approvals policy<br/>(pure: Recommendation + current config)
  participant DB as SQLite: business rows
  participant AU as Audit chain

  A->>API: POST /api/recommendations/{id}/decision<br/>accept / modify / reject + rationale (recommendation:decide)
  API->>DB: load the Recommendation
  alt not pending_advisor
    API-->>A: 409
  else reject or modify without a rationale
    API-->>A: 422
  else accept
    API->>P: plan(), then next_status after "advisor"
    P-->>API: pending_compliance, pending_committee or approved
  else modify
    API->>API: validate the Trade Lines, re-evaluate drift and Suitability (deterministic engine)
    Note over API: Original becomes superseded. Version v+1 is created at pending_advisor<br/>and comes back to the Advisor.
  else reject
    API->>API: resulting status rejected
  end
  API->>AU: decision_recorded (its commit carries the Decision row and the status change)
  opt modify
    API->>AU: recommendation_modified, then suitability_evaluated for the new version
  end
  API-->>A: Decision, resulting Recommendation, rules newly in breach

  opt pending_compliance (a Suitability Rule in breach)
    CO->>API: GET /api/approvals: breached rules, affected Trade Lines, Restrictions
    CO->>API: POST /api/recommendations/{id}/compliance<br/>approve / block + rationale (compliance:decide)
    API->>API: 409 unless waiting for Compliance, 422 without a rationale
    API->>P: next_status after "compliance" (current thresholds)
    alt approve
      API->>AU: exception_approved (status becomes pending_committee or approved)
    else block
      API->>AU: exception_blocked (status becomes rejected)
    end
    API-->>CO: Decision and Recommendation
  end

  opt pending_committee (high-impact)
    IC->>API: GET /api/approvals: turnover, Trade Lines and the reasons it is high-impact
    IC->>API: POST /api/recommendations/{id}/committee<br/>approve / reject + rationale (committee:decide)
    API->>API: 409 unless waiting for the Committee, 422 without a rationale
    API->>AU: decision_recorded: committee_approve (approved) or committee_reject (rejected)
    API-->>IC: Decision and Recommendation
  end
  Note over A,AU: Each Decision's Audit Event names the Recommendation's previous event as its parent,<br/>so lineage runs from the Analysis Run through every Decision.
```

[Detailed 6.2 tiered decisions controls and failure paths](appendices.md#e19-62-tiered-decisions-controls-and-failure-paths).

## 6.3 Report ingestion to Insight Review

A Research Analyst uploads a Report. The platform splits it into pages and makes one LLM call to extract candidate Insights. Code keeps a candidate only if its subject is in the taxonomy and its quoted passage really appears on the cited page. Every kept Insight starts `pending`, and only an Insight the Analyst approves in Insight Review can influence anything downstream. After approval, the passage is checked again whenever a narrative cites it, by the Grounding validator.

```mermaid
sequenceDiagram
  autonumber
  actor RA as Research Analyst
  participant API as API: reports router
  participant S as Research and Insights service
  participant DB as SQLite: business rows
  participant LLM as ModelLlm (capture) → live<br/>or replay Model
  participant EX as LLM Exchanges
  participant AU as Audit chain
  participant G as Grounding validator

  RA->>API: POST /api/reports, PDF or text file (report:upload)
  API->>API: over 20 MiB: 413
  API->>S: ingest()
  S->>S: split into pages: pypdf per PDF page, form feeds in text
  Note over S: Not a PDF or UTF-8 text, no extractable text,<br/>or over 400,000 characters: 422, nothing stored
  S->>DB: Report and its pages, commit
  S->>AU: report_ingested (actor: the Analyst)
  S->>LLM: insight extraction, every page labelled [Page n]
  LLM->>EX: store Exchange (own DB session, commit)
  LLM-->>S: reply with Exchange id and hash, or LlmError
  alt LlmError (replay miss included) or the reply fails the schema
    S->>DB: extraction_status failed, commit
    S->>AU: insight_extracted, outcome failed, carrying the Exchange ref
    API-->>RA: 201 Report marked extraction failed, no Insights
  else a reply that fits the schema
    S->>S: keep a candidate only if its subject is in the taxonomy, its page exists<br/>and its passage appears on that page (normalised). Others are dropped with a reason.
    S->>AU: insight_extracted, outcome ok, count kept, dropped reasons, carrying the Exchange ref
    S->>DB: each kept Insight, status pending, linked to that event
    API-->>RA: 201 Report with its pending Insights
  end

  Note over RA,API: Insight Review
  RA->>API: GET /api/reports/{id}/pages/{page}: the cited page beside the Insight
  RA->>API: POST /api/insights/{id}/decision, approve / reject + note (insight:approve)
  API->>S: decide()
  alt Insight already reviewed
    API-->>RA: 409
  else pending
    S->>DB: status approved or rejected, decided by and when, commit
    S->>AU: insight_approved or insight_rejected (parent: insight_extracted)
    API-->>RA: the Insight
  end

  Note over S,G: Downstream, only approved Insights are retrievable
  Note over S: The next Analysis Run (6.1) uses approved Insights for the<br/>Opportunity component, Research Tilts and narratives
  S->>G: a narrative Claim cites Report id, page and quote
  G->>DB: Report and page exist, quote appears on that page?
  G->>AU: grounding_checked (+ claim_ungrounded for a quote not on its page)
```

[Detailed 6.3 report ingestion to insight review controls and failure paths](appendices.md#e20-63-report-ingestion-to-insight-review-controls-and-failure-paths).

## 6.4 Assistant Question

Any role holding `assistant:use` can ask the Assistant about the screen in view. The browser sends only the Question and a screen identity (kind, entity ids, selected item), never screen data. The server rebuilds the Screen Context through the same service the screen itself uses, filtered by the user's permissions. The context carries Client ids only, never names or emails.

```mermaid
sequenceDiagram
  autonumber
  actor U as Any role
  participant SPA as React SPA: Assistant drawer
  participant AS as Assistant service
  participant SC as Screen Context builders
  participant AG as Agent loop (pydantic-ai)<br/>read-only tools, output validator
  participant LLM as Capture → live<br/>or replay Model
  participant EX as LLM Exchanges
  participant G as Grounding validator
  participant AU as Audit chain

  U->>SPA: ask a Question on the current screen
  SPA->>AS: POST /api/assistant/questions: Question + screen identity (assistant:use)
  AS->>AS: usage limits: 400 or 429 stores nothing, calls nothing
  AS->>SC: build(screen identity, user)
  SC-->>AS: Screen Context (text, figures, hash), or none
  alt none: unknown, or not readable by this user
    AS->>AS: refused without a model request (existence is not revealed)
  else a Screen Context
    AS->>AG: run: platform brief, Screen Context (data, not instructions),<br/>recent Questions and Answers, the Question. Request budget 6
    AG->>LLM: request 1 (tool definitions offered)
    LLM->>EX: Exchange, Trajectory position 0 (own session, commit)
    LLM-->>AG: tool call look_up_portfolio(C004)
    AG->>SC: build the Portfolio screen for this user, figures named portfolio.C004.*
    alt the user may open it
      SC-->>AG: that screen's Screen Context, its figures join the citable set
    else not permitted, or does not exist
      SC-->>AG: "not found or not permitted for your role"
    end
    Note over AG: The step goes into the "How I answered" summary
    AG->>LLM: request 2 (messages so far, tool result included)
    LLM->>EX: Exchange, position 1
    LLM-->>AG: draft reply
    AG->>G: output validator: PII scan, then ground each Claim against<br/>the Screen Context's and every lookup's figures
    alt a Client's name or email in the draft
      G-->>AG: PII: the run ends, no retry
    else ungrounded Claims, first draft
      G-->>AG: the failing Claims and their issues
      AG->>LLM: request 3: "These Claims are not grounded…" (self-correction, once)
      LLM->>EX: Exchange, position 2
      LLM-->>AG: corrected reply, accepted whatever its grounding
    else grounded
      G-->>AG: accepted
    end
    AG-->>AS: final reply, or PII, budget_exhausted, LlmError
    opt answered with Claims
      AS->>G: record the grounding of the final Claims
      G->>AU: grounding_checked (+ claim_ungrounded per flagged Claim)
    end
  end
  AS->>AS: append the turn: outcome, Answer, final Exchange ref, Trajectory summary
  AS->>AU: assistant.answered, .refused or .failed, anchoring exchanges [pos 0, 1, 2] by id and hash
  AS-->>SPA: the turn, with "How I answered": lookups, self-correction, requests used of the budget, tokens
  SPA-->>U: Answer with grounding marks, the Out-of-Scope Refusal, or the failure message
```

[Detailed 6.4 assistant question controls and failure paths](appendices.md#e21-64-assistant-question-controls-and-failure-paths).
