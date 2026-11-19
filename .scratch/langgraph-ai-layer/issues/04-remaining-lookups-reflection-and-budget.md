Status: resolved
Blocked by: 03

# All lookups, reflection edge, PII rejection and request budget

## What to build
- Port every remaining lookup as a `@tool` in the `ToolNode`, keeping its least-privilege behaviour: "not permitted" replies, and identical replies for unknown and forbidden entities.
- Implement the `validate` node and its conditional edge, following the documented evaluator-optimizer loop. It allows at most one return to `agent` naming the ungrounded Claims; Claims still ungrounded after that retry are kept and flagged.
- On PII failure, go to END with a rejection and no retry.
- Add the request budget: a model-call counter in graph state, checked in routing before each `agent` run, which ends the turn with `budget_exhausted` (`APP_ASSISTANT_REQUEST_LIMIT`, default 6).

Check the APIs against current docs via Context7.

## Acceptance criteria
- [x] Behaviour matches ADR-0010 for permissions, grounding, PII and budget
- [x] Reflection, PII and budget paths are explicit edges in the graph
- [x] The async-tool guard is still enforced, if tools are async (tools are sync: nothing to guard, ADR-0011)
- [x] Out-of-Scope Refusals are unchanged
