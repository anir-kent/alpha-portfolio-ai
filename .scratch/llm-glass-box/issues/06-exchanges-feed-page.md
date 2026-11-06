# 06: LLM Exchanges feed page

**What to build:** Reviewers open a new LLM Exchanges page and watch the model's activity as it happens. The page lists Exchanges newest first with the review filters, and a live-tail toggle streams new ones in while an analysis runs, falling back to the normal list if the stream is unavailable. It is visible only to roles holding `llm:read` and follows the existing frosted-glass design system.

**Blocked by:** 05, 02

**Status:** done

- [x] An "LLM Exchanges" item appears in the GATEWAY navigation group only for roles holding `llm:read`, and the route is not reachable for other roles
- [x] The feed shows time, task, prompt version, model, a live/recorded pill, outcome, latency, token counts and the linked Recommendation or Portfolio, with figures right-aligned in monospace
- [x] The filter ribbon covers task, prompt version, mode, outcome and date range, using the existing segmented controls and debossed fields
- [x] Starting an analysis with live tail on makes new Exchanges appear without reloading; turning it off or losing the stream falls back to the list without losing rows
- [x] Replayed Exchanges show tokens and latency as "n/a (replayed)" and failed ones show the error summary on the row
- [x] Empty, loading and error states are handled
- [x] The manual E2E checklist gains items for the feed and live tail
- [x] `npm run typecheck` and `npm run build` pass
