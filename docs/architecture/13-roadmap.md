# Target / Production Roadmap

**Proposed target state; not implemented.** Today's topology is [§7](07-deployment-view.md). The logical target is a built SPA behind HTTPS, federated identity, stateless API workers, managed PostgreSQL, shared run coordination, a governed LLM gateway, secret management and external audit anchoring. Azure maps these to App Service (AKS alternative), Entra ID, Azure Database for PostgreSQL and Key Vault. Multiple workers require the shared-state gate first.

[Detailed production deployment boundaries and rollout gates](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) preserves both target diagrams, Azure mapping, proposed owners and measurable exit evidence. Real-data admission depends on the applicable identity, persistence, evidence and provider-review gates; a cloud deployment alone does not establish production readiness.

Performance and scalability remain [current-version non-goals](10-quality-requirements.md#103-non-goals). The roadmap establishes targets before a production commitment.

## Roadmap items

### RM-01 Identity and browser security

Addresses R-01/02/03: federated sign-in/MFA, production cookie defaults, CSRF protection and login throttling. Gate: browser and role tests pass with demo accounts removed. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.

### RM-02 Managed persistence and migrations

Addresses R-05 and TD-07: managed PostgreSQL, versioned migrations, separated database roles and tested backup/restore. Gate: data migration and recovery are evidenced. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.

### RM-03 Shared state and run recovery

Addresses R-04/06 and scalability: durable run progress and a global run lease before multiple workers. Gate: concurrent-start and process-loss tests preserve one run and recover SSE. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.

### RM-04 Complete and atomic audit evidence

Addresses TD-03/04/05: independently durable Exchange capture, audit anchors for every tilt and atomic recording. Gate: failure injection leaves complete evidence and no actionable partial Recommendation. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.

### RM-05 External audit anchoring

Addresses R-09: retain chain heads outside the application database under separate write-once controls. Gate: verification detects a full local-chain rewrite against the external anchor. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.

### RM-06 Governed LLM gateway

Addresses R-08: approved LiteLLM routes, provider terms, quotas and evaluated fallbacks. Gate: outage tests preserve deterministic results and all attempted-call evidence. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.

### RM-07 Assistant cost and operational telemetry

Addresses R-10 and TD-01: token/cost budgets, structured logs, metrics and traces. Gate: spend boundaries and injected-failure alerts work without sensitive operational logs. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.

### RM-08 Frontend regression coverage

Addresses TD-02: component and browser tests for permissions, Decisions, research, Assistant and SSE. Gate: deliberately incorrect actions fail CI. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.

### RM-09 Model-aware reproducible recordings

Addresses TD-06/08: model-aware recording keys and controlled re-recording with credentials and spend ceilings. Gate: substantive model, prompt and tool-result changes miss stale recordings. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.

### RM-10 Controlled data pilot and capacity gate

Addresses R-07 and capacity non-goals: data-protection review, provider terms, retention, licensed fresh data and agreed workload/SLO/recovery targets. Gate: controlled pilot, load, restore and failover evidence meets those targets. See the [detailed gate](appendices.md#e34-production-deployment-boundaries-and-rollout-gates) for risk links, owner and acceptance evidence.
