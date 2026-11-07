# 02: Tracer bullet: ask a Question on the Portfolio screen

**What to build:** An Advisor on the Portfolio screen opens the Assistant drawer, asks a Question, and gets a Markdown Answer built from that Portfolio's Screen Context through one LLM call. If the model reports the Question as out of scope, the Advisor gets the fixed Out-of-Scope Refusal instead. Every turn is stored and anchored in the audit chain (ADR-0006). See spec: Access, Screen identity and Screen Context, Prompt and LLM call, Conversation and persistence, API contract (ask).

**Blocked by:** None (can start immediately)

**Status:** resolved

- [x] The `assistant:use` permission is granted to every role; the RBAC matrix test covers it; without it, ask returns `403`, the denial is audited, and the drawer is hidden
- [x] Posting a Question with a Portfolio screen identity creates a Conversation tied to the login session and an append-only turn (Question, screen identity, Screen Context hash, outcome, Answer, Exchange reference)
- [x] The Portfolio Screen Context holds Holdings, Target Allocation, Asset-Class Drift and Portfolio Drift, Restrictions, Risk Profile and the latest Analysis Run summary, drawn from the same services as the Portfolio screen
- [x] The captured prompt contains no Client name or email, even for an advisor holding `client:pii`
- [x] A Portfolio the user can't read gets the Out-of-Scope Refusal and reveals nothing about whether it exists
- [x] The prompt uses `assistant_answer@v1`, made of the scope policy, the read-only rule, the platform brief, the Screen Context and the Question; the reply schema is `in_scope`, `answer_markdown`, `claims` and `follow_up_questions`
- [x] `in_scope: false` returns the fixed refusal text (never the model's text) and writes `assistant.refused`; an answered turn writes `assistant.answered`; both carry the Exchange reference, and chain verification passes
- [x] The drawer sits in the app shell, names the current context, sends the Question, shows a "thinking…" state and renders sanitised Markdown with no raw HTML
- [x] `npm run typecheck` passes; the manual E2E checklist has items for asking a Question and seeing an Answer
