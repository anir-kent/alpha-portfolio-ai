# 08: Remaining lookups with least privilege

**What to build:** The Assistant can follow a Question to any screen the asking user could open, and no further. It adds the read-only lookups `look_up_queue(filters?)`, `look_up_recommendation(recommendation_id)`, `look_up_approvals()`, `look_up_audit(filters?)` and `look_up_governance()` over the existing Screen Context builders, plus a new `list_approved_insights(sector?)` that returns only Insights with an approved Insight Review. The exchanges screen is not exposed. Spec: "Assistant agent → Tools".

**Blocked by:** 07 (Assistant tracer bullet: one lookup, end to end)

**Status:** resolved

- [x] All tools are `async def` and pass the coroutine guard
- [x] Each tool returns "not found or not permitted for your role" exactly where the matching screen would be forbidden or the entity is absent, identically in both cases
- [x] `list_approved_insights` never returns an Insight that is awaiting review or rejected, and its results carry Report citations usable for grounding
- [x] A test for every tool and every role asserts that no Client name or email is ever returned and that permission outcomes match the screens (extends the RBAC and prompt-PII guard tests)
- [x] The system text and prompt version are updated to describe every tool
- [x] "How I answered" result summaries are meaningful for each tool (for example "queue: 40 rows, showing 25", "recommendation 7: 5 trade lines, 1 breach")

## Comments

- Lookup figures never overwrite the screen's or each other's. A Portfolio's are `portfolio.<id>.`, a Recommendation's `portfolio.<Portfolio>.recommendation.<id>.`, and the filtered Queue and Audit lookups `lookup.<n>.` (n is the call's place in the turn). Approvals and governance keep their screen names, which match their screens. Citation chips route every prefix back to its source screen.
- The every-role matrix drives the Agent directly with the deps `ask` gives it, because a Research Analyst can open no screen the Assistant is asked from. Behaviour tests go through the HTTP API.
- `list_approved_insights` leaves out who decided and their note (free text by a human). It has no citable figures: grounding uses its Report passages.
- Prompt is `assistant_answer@v5`. Scripted Suggested Question fixtures were regenerated offline. The live eval is still pending (strict xfail now on v5).
