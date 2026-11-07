# 04: §1–§4: Introduction & goals, Constraints, Context (C4 L1), Solution strategy

**What to build:** An ARB reviewer reads the opening sections and understands what the platform is, for whom, and its boundary. §1 states the purpose, stakeholders and the ranked quality goals (Auditability, Explainability, Human control / safety, Data protection, Reproducibility) with performance and scalability as explicit non-goals. §2 lists constraints (never executes trades, synthetic Clients, committed market data snapshot, single process, recorded/live LLM modes). §3 has the C4 System Context diagram (human roles, platform, LLM endpoint, Twelve Data via manual refresh). §4 summarises the shaping decisions, each linked to ADR-0001…0008.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] §1 stakeholder table covers the eight RBAC roles and the review audiences
- [ ] Quality goals ranked exactly as agreed; non-goals stated
- [ ] §3 C4 L1 diagram in Mermaid renders under `check`
- [ ] §4 links every ADR rather than restating it
- [ ] Every factual claim verified against the code on the baseline commit; `check` green
