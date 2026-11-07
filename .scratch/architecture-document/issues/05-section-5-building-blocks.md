# 05: §5 Building blocks: C4 L2 Containers and L3 Components

**What to build:** An engineer or reviewer sees the platform's structure at two zoom levels. C4 L2: React SPA, FastAPI API process, SQLite store, committed data files (market snapshot, fund look-through, seeds, LLM recordings), LLM endpoint. C4 L3 for the API process: deterministic engine, Research & Insights, AI-on-Recommendations steps, Recommendations & Decisions, approvals policy, Grounding validator, audit chain, LLM Exchange capture, Assistant (incl. Screen Context), governance, config, health, auth/RBAC. Each component gets a responsibility line at navigation altitude. The tiered-approval policy is described exactly as the code applies it (Advisor always; Compliance on Suitability breach; Investment Committee when turnover or a single Trade Line crosses configured thresholds; re-plan on threshold change). Includes the Research Analyst UI.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] C4 L2 and L3 Mermaid diagrams render under `check`
- [ ] Responsibility table for every component; no file paths beyond top-level orientation
- [ ] Tiered-approval description verified against the approvals policy and its tests
- [ ] Only built behaviour described; `check` green
