# 6. Runtime View

Four flows carry the platform's critical behaviour. Each diagram shows two kinds of evidence: where Audit Events are appended to the chain (the **Audit chain** lane) and where LLM Exchanges are stored (the **LLM Exchanges** lane). Both are tables in the one SQLite file ([ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md)). They get their own lanes because they are the record an Auditor relies on.

Some rules hold in all four flows:

- **One appended event, one commit.** Every Audit Event is appended under a process-wide lock and committed on its own ([ADR-0002](../adr/0002-hash-chained-append-only-audit-log.md)). Business rows flushed before that event commit with it.
- **The LLM Exchange comes first.** Every LLM call goes through one capturing wrapper. The wrapper stores the LLM Exchange, for a reply or an error, before the caller writes the Audit Event that references it by id and hash. If the LLM Exchange cannot be stored, the call fails ([ADR-0004](../adr/0004-llm-exchanges-stored-separately-anchored-in-audit-chain.md)).
- **One call per LLM step.** Each step is a single, schema-bound request, with no agent loop and no retrieval ([ADR-0007](../adr/0007-llm-steps-are-single-schema-bound-calls.md)).
- **Replay misses fail.** In recorded mode a prompt with no recording raises a replay miss. It is never answered with a guess, and it fails the call like any other LLM error.
- **Denials are audited.** A role that lacks the endpoint's permission gets `403`, and an `access_denied` Audit Event is written. The diagrams leave this out.

The components named in the lanes are described in [5.2 Level 2: API process components](05-building-block-view.md#52-level-2-api-process-components). Domain terms are defined in [`GLOSSARY.md`](../../GLOSSARY.md).

## 6.1 Analysis Run

An Advisor or Relationship Manager (`analysis:run`) starts an Analysis Run. The run executes on a background thread, and its Run Step progress streams to the browser over server-sent events. Only one run is in flight per process ([ADR-0005](../adr/0005-run-step-progress-in-process.md)).

The run commits in three phases, which are commit boundaries, not Run Steps ([ADR-0009](../adr/0009-analysis-run-recording-commits-per-audit-event.md)):

1. **Scoring.** Loading inputs and scoring every Portfolio are one write transaction. It includes the Research Tilt LLM Exchanges, each stored under a savepoint.
2. **Recording.** The `record_run` Run Step commits one Audit Event at a time.
3. **Completion.** A final commit marks the run `completed`, and only then does it become the current result.

The two narrative Run Steps run after that commit, so a failing LLM cannot undo a recorded run.

```mermaid
sequenceDiagram
  autonumber
  actor U as Advisor / Relationship Manager
  participant SPA as React SPA
  participant API as API: analysis router
  participant R as AnalysisRuns + ProgressRegistry<br/>(process memory)
  participant W as Run thread<br/>(run_analysis)
  participant DB as SQLite: business rows
  participant LLM as CapturingLlm → endpoint<br/>or recordings
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

On a failed narrative, no grounding check runs: the failed row and a `status: failed` event are written in its place. The run's outcome is `completed` only if every Run Step is done. It is `completed_with_warnings` if `record_run` is done but an AI step failed, and `failed` otherwise.

| Failure path | What happens |
| --- | --- |
| A second start while a run is in flight | `409` with the in-flight run's snapshot. The SPA follows that run's progress; no second run starts. |
| A Load inputs or Score Portfolios step fails | That Run Step is marked failed and every later one skipped. The transaction never commits, so nothing it wrote survives, the Research Tilt LLM Exchanges stored under its savepoints included. Only the run row remains, with outcome `failed`. |
| The Research Tilt call fails, or a replay miss in recorded mode | An LLM Exchange with outcome `error` is still stored. That Portfolio gets no tilt. If a Recommendation is drafted, its `research_tilt_proposed` event records `status: failed`. Scoring carries on. |
| A Research Tilt is assessed, but the rebalance plan yields no Trade Lines | No Recommendation is drafted, so no `research_tilt_proposed` event is written. The tilt's LLM Exchange still commits with the scoring transaction, but no Audit Event references it. This is a known gap in anchoring every LLM Exchange in the chain ([ADR-0004](../adr/0004-llm-exchanges-stored-separately-anchored-in-audit-chain.md)). |
| A narrative call fails, or its reply fails the schema | The narrative row is stored as failed, with a `status: failed` Audit Event carrying the LLM Exchange reference. The Run Step is marked failed and the outcome is `completed_with_warnings`. The Queue shows "Narrative unavailable (AI step failed; scores are unaffected)." |
| The process dies mid-run | At startup the run row is marked `interrupted`. If the process died during `record_run`, committed scoring rows and some Audit Events remain. The run is never current, but its Recommendations are visible. This is the gap that [ADR-0009](../adr/0009-analysis-run-recording-commits-per-audit-event.md) records. |

## 6.2 Tiered Decisions

Every Recommendation starts at `pending_advisor`. The approvals policy decides which further steps it needs:

- **Compliance** when its post-trade Suitability is in breach. The Compliance Officer approves a Suitability Exception or blocks the Recommendation.
- **Investment Committee** when its turnover, or any single Trade Line, is at or above the configured threshold.

The policy is a pure function of the Recommendation and the configuration in force at the moment of each Decision. A threshold change between steps therefore re-plans what remains. Each Decision is accepted only at the step the Recommendation is waiting at, so no step can be skipped. No LLM is called on this path, so no LLM Exchange is written. "Approved" means cleared to act outside the platform; nothing is executed.

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

| Failure path | What happens |
| --- | --- |
| A Decision at the wrong step, or on a Recommendation already decided or superseded | `409`, naming the status the Recommendation is in. Nothing is written. |
| A missing rationale (reject or modify at the Advisor step; every Compliance and Committee Decision) | `422`. Nothing is written. |
| A modification with invalid Trade Lines (unknown Instrument or Account, a quantity that is not a positive whole number, a duplicate line, selling more than is held) | `422`, with the engine's validation message. |
| A new Analysis Run while a Recommendation is open | The run supersedes it with a `recommendation_superseded` event, and any later Decision on it gets `409` (see [6.1](#61-analysis-run)). |

## 6.3 Report ingestion to Insight Review

A Research Analyst uploads a Report. The platform splits it into pages and makes one LLM call to extract candidate Insights. Code keeps a candidate only if its subject is in the taxonomy and its quoted passage really appears on the cited page. Every kept Insight starts `pending`, and only an Insight the Analyst approves in Insight Review can influence anything downstream. After approval, the passage is checked again whenever a narrative cites it, by the Grounding validator.

```mermaid
sequenceDiagram
  autonumber
  actor RA as Research Analyst
  participant API as API: reports router
  participant S as Research and Insights service
  participant DB as SQLite: business rows
  participant LLM as CapturingLlm → endpoint<br/>or recordings
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

| Failure path | What happens |
| --- | --- |
| Unreadable or oversized file | `413` over 20 MiB. `422` for a file that is not a PDF or UTF-8 text, a scanned PDF with no text, or more than 400,000 characters. Nothing is stored and no LLM call is made. |
| The extraction call fails, or a replay miss in recorded mode | The Report is kept with extraction status `failed`. An LLM Exchange with outcome `error` and an `insight_extracted` event with outcome `failed` are written. The Analyst sees the failure on the Report. |
| The LLM invents a subject, page or passage | That candidate is dropped before it becomes an Insight, and the reason is recorded on `insight_extracted`. |
| A second Insight Review of the same Insight | `409`. The first review stands. |
| A narrative misquotes an approved Report | The Grounding validator flags the Claim (`quote_not_found`) and writes `claim_ungrounded`. Only Grounded Claims reach a memo or summary. |

## 6.4 Assistant Question

Any role holding `assistant:use` can ask the Assistant about the screen in view. The browser sends only the Question and a screen identity (kind, entity ids, selected item), never screen data. The server rebuilds the Screen Context through the same service the screen itself uses, filtered by the user's permissions. The context carries Client ids only, never names or emails. Each Question gets exactly one LLM call. Every turn, whether answered, refused or failed, is stored append-only in the login session's Conversation, with one Audit Event ([ADR-0006](../adr/0006-assistant-conversations-persisted-and-audited.md)).

```mermaid
sequenceDiagram
  autonumber
  actor U as Any role
  participant SPA as React SPA: Assistant drawer
  participant API as API: assistant router
  participant AS as Assistant service
  participant SC as Screen Context builder
  participant DB as SQLite: business rows
  participant LLM as CapturingLlm → endpoint<br/>or recordings
  participant EX as LLM Exchanges
  participant G as Grounding validator
  participant AU as Audit chain

  U->>SPA: ask a Question on the current screen
  SPA->>API: POST /api/assistant/questions: Question + screen identity (assistant:use)
  API->>AS: ask()
  AS->>DB: count this Conversation's turns, and the user's turns in the last hour
  break Question too long, or a usage limit is hit
    AS-->>SPA: 400 over the length limit, 429 per-Conversation limit,<br/>or 429 per-user hourly limit with Retry-After
    Note over AS,AU: Nothing stored, no LLM call, no Audit Event
  end
  AS->>SC: build(screen identity, user)
  SC->>DB: read through the screen's own service, filtered by the user's permissions,<br/>Client ids only, list screens capped at the configured row budget
  SC-->>AS: Screen Context (text, figures, hash), or none
  alt none: unknown, or not readable by this user
    AS->>AS: outcome refused, without an LLM call (existence is not revealed)
  else a Screen Context
    AS->>LLM: one request: platform brief, Screen Context (data, not instructions),<br/>recent Questions and Answers (none for a Suggested Question), the Question
    LLM->>EX: store Exchange (own DB session, commit). If storing fails, the call fails.
    LLM-->>AS: reply with Exchange id and hash, or LlmError
    alt LlmError
      AS->>AS: failed: replay_miss ("Only Suggested Questions work in replay mode") or llm_error
    else the reply fails the schema
      AS->>AS: failed: unreadable_reply
    else in_scope is false
      AS->>AS: refused: the model's text is discarded, the Out-of-Scope Refusal is shown
    else any Client's name or email in the reply
      AS->>AS: failed: pii (the Answer is never checked, stored or shown)
    else in scope and clean
      opt the reply has Claims
        AS->>G: check the Claims against the Screen Context's figures
        G->>AU: grounding_checked (+ claim_ungrounded per flagged Claim)
      end
      AS->>AS: answered, every Claim with its grounding result
    end
  end
  AS->>DB: append the turn: Question, screen identity, context hash, outcome, Answer, Exchange ref
  AS->>AU: assistant.answered, assistant.refused or assistant.failed (commits with the turn)
  AS-->>SPA: the turn (a failed turn carries only a fixed message)
  SPA-->>U: Answer with grounding marks, the Out-of-Scope Refusal, or the failure message
```

| Failure path | What happens |
| --- | --- |
| A usage limit is hit | `400` for an over-long Question. `429` once the Conversation reaches its Question limit (log out and back in to start a new one). `429` with `Retry-After` once the user reaches the hourly limit. Turns count whatever their outcome. Nothing is stored and the model is not called. |
| The screen names something the user cannot read, or that does not exist | `refused`, without an LLM call. The user sees the same Out-of-Scope Refusal either way, so the reply does not reveal whether the item exists. |
| A replay miss in recorded mode | `failed` with reason `replay_miss`. The user is told that only Suggested Questions work in recorded mode (the message says "replay mode"). Suggested Questions are sent without history, so their recordings replay whatever was asked before them. |
| Guardrail refusal: the model judges the Question out of scope | `refused`. The model's text is discarded and the fixed Out-of-Scope Refusal is shown. The LLM Exchange keeps what the model said. |
| The PII backstop fires | `failed` with reason `pii`. The Answer is not grounded, stored or shown. The Audit Event records the reason; the user sees only the generic failure message. |
| An ungrounded Claim | The Answer is shown with that Claim flagged. A `claim_ungrounded` Audit Event is written. |
