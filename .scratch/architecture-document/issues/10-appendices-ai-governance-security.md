# 10: Appendices: AI Governance and Security summary (+ sample-password placeholder)

**What to build:** Model risk and InfoSec reviewers get their own appendices. AI Governance: model inventory (model of record `anthropic/claude-sonnet-5.5` via OpenRouter behind an OpenAI-compatible endpoint, temperature omitted by default, swappable; each task and prompt version), the engine/LLM boundary, a guardrails table (where it acts, what happens when it fires), eval set description (categories, metrics, scripted-model CI run, manual live run) with the live results on the model of record quoted from the eval results file (30/30, `assistant_answer@v3`), control mapping to SR 11-7 (primary) and NIST AI RMF (secondary), and an EU AI Act classification note. Wording is "addresses / maps to", never "compliant" or "certified". Security summary: authentication, server-only RBAC with denial audit (links the generated matrix), secrets handling, prompt-injection defences, pointer to §11 gaps. The committed example environment file's sample password is replaced with an obvious placeholder.

**Blocked by:** 01, 02

**Status:** resolved

- [x] Guardrails table covers Grounding, Research Tilt bound, approved-Insights-only, fenced Report passages, Out-of-Scope Refusal, permission-filtered Screen Context, PII check, usage limits, fail-closed Exchange capture
- [x] SR 11-7 and NIST AI RMF mapping tables; EU AI Act note; no compliance or certification claim anywhere
- [x] Eval results quoted from the live run on the model of record, with model, prompt version and run date
- [x] Example environment file contains no realistic credential
- [x] `check` green

## Comments

**2026-11-08, implementation (Codex).**
- Filled Appendices A–D with the engine/LLM boundary, nine guardrails and their failure behavior/limits, task/model inventory, evaluation method and results, framework mappings and security/threat summary. Links point to code, the generated prompt/permission/limit tables and §11 gaps.
- Preserved the required historical model-of-record result directly from `data/assistant_eval.json` at `a6802bd4ad92cd4ce81911daf32de5cbbe9e59e7`: 30/30, `assistant_answer@v3`, 2026-11-07T14:03:14+00:00. Also quoted the current file: 33/33, `assistant_answer@v5`, 2026-11-08T08:57:45+00:00, on the same model. The appendix distinguishes these runs and describes the current bounded Assistant; no live eval was rerun.
- Kept SR 11-7 as the spec's primary mapping, with an official-source note that SR 26-2 superseded it on 17 April 2026. Added NIST AI RMF 1.0 mapping and a preliminary EU AI Act classification inference with legal-review limits.
- Replaced the example seed password with `REPLACE_WITH_YOUR_OWN_DEMO_PASSWORD`.
- Independent review: Standards zero findings; Spec found two overstatements, both corrected and re-reviewed: wire evidence is optional on replay; raw reply/error key redaction does not generically sanitize parsed content or user text.
- Verified: architecture document `check` including Mermaid OK; focused architecture/eval tests 31 passed; full suite 739 passed, 1 skipped (10 deprecation warnings); Ruff lint/format and mypy (112 source files) clean; frontend lint (39 existing Fast Refresh warnings), format and type checks pass.
