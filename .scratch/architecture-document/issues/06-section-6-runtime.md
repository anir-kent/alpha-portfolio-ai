# 06: §6 Runtime view: four sequence diagrams

**What to build:** A reviewer follows the critical flows end to end: (1) Analysis Run with Run Step progress over SSE, one run at a time, atomic scoring transaction, AI steps; (2) tiered approval of a Recommendation through Advisor, Compliance and Committee Decisions with Audit Events; (3) Report upload → page split → insight extraction → human Insight approval → Grounding; (4) an Assistant Question: permission-filtered Screen Context rebuilt server-side, one LLM call, scope/grounding/PII checks, stored turn and Audit Event, usage limits.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Four Mermaid sequence diagrams render under `check`
- [ ] Each diagram shows where Audit Events and LLM Exchanges are written
- [ ] Failure paths shown where they matter (replay miss, guardrail refusal, 409 on concurrent run, 429 usage limit)
- [ ] Verified against routers and services on the baseline commit; `check` green
