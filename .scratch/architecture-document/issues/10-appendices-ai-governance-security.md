# 10: Appendices: AI Governance and Security summary (+ sample-password placeholder)

**What to build:** Model risk and InfoSec reviewers get their own appendices. AI Governance: model inventory (model of record `anthropic/claude-sonnet-5.5` via OpenRouter behind an OpenAI-compatible endpoint, temperature omitted by default, swappable; each task and prompt version), the engine/LLM boundary, a guardrails table (where it acts, what happens when it fires), eval set description (categories, metrics, scripted-model CI run, manual live run) with the live results on the model of record quoted from the eval results file (30/30, `assistant_answer@v3`), control mapping to SR 11-7 (primary) and NIST AI RMF (secondary), and an EU AI Act classification note. Wording is "addresses / maps to", never "compliant" or "certified". Security summary: authentication, server-only RBAC with denial audit (links the generated matrix), secrets handling, prompt-injection defences, pointer to §11 gaps. The committed example environment file's sample password is replaced with an obvious placeholder.

**Blocked by:** 01, 02

**Status:** ready-for-agent

- [ ] Guardrails table covers Grounding, Research Tilt bound, approved-Insights-only, fenced Report passages, Out-of-Scope Refusal, permission-filtered Screen Context, PII check, usage limits, fail-closed Exchange capture
- [ ] SR 11-7 and NIST AI RMF mapping tables; EU AI Act note; no compliance or certification claim anywhere
- [ ] Eval results quoted from the live run on the model of record, with model, prompt version and run date
- [ ] Example environment file contains no realistic credential
- [ ] `check` green
