# 10. Quality Requirements

This section turns the ranked quality goals of [1.2 Quality goals](01-introduction-and-goals.md#12-quality-goals) into scenarios a reviewer can check. Each scenario states a stimulus, the system's response and a measure that is either met or not. The linked detailed catalog names the automated tests that assert each scenario in CI. A scenario describes what the code on the baseline commit does. Where a goal has a known gap, the gap is in [11. Risks and Technical Debt](11-risks-and-technical-debt.md), not glossed over here.

## 10.1 Quality tree

Goals are ranked. When two conflict, the higher one wins. For example, an LLM Exchange that cannot be stored fails its AI step (Auditability) even though the step's answer was available (Explainability).

[Detailed quality tree](appendices.md#e32-quality-tree). Ranked goals and concrete scenarios follow below.

## 10.2 Quality scenarios

| Goal | Stimulus and response | Measure / limit |
| --- | --- | --- |
| Auditability | Alter an Audit Event or an anchored Exchange; `GET /api/audit/verify` checks hashes and lineage | `valid: false` names the first broken event. A privileged rewrite of the entire database still needs an external anchor (R-09). Capture gaps remain TD-03/04/05. |
| Explainability | The model supplies an unsupported Claim; Grounding flags it and excludes it from the memo | Zero ungrounded Claims in the memo. Assistant free-form prose is not universally fact-checked. |
| Human control / safety | A Recommendation needs approval tiers; the policy enforces Advisor, then Compliance on breach, then Committee at threshold | No route to Approved without every required human Decision; out-of-order Decisions receive 409 and wrong-role endpoint calls 403. Approved executes nothing. |
| Data protection | Build Client identity from application records for a prompt or Screen Context | Representative fixture prompts contain zero stored Client names/emails, even for `client:pii` roles. Arbitrary Questions/history and Reports are not sanitized (§8.9). A stored Client full name/email in an Assistant reply fails the turn. |
| Reproducibility | Repeat a seeded run offline, or change a prompt/tool result | Same seed yields identical Clients/Holdings; committed recordings replay offline. Changed requests miss rather than reuse stale results. Model identity is not in the recording key (TD-06). |

[Detailed quality scenario and test catalog](appendices.md#e14-quality-scenario-and-test-catalog). This preserves all scenario ids, stimuli, responses, measures and exact CI test references, including bounded Research Tilts and approved-Insights-only checks. Tests run at API and engine seams; recorded fixtures keep normal CI offline. Live model evidence is separate in Appendix B.

## 10.3 Non-goals

**Performance and scalability are non-goals for this version.** The platform runs as one API process on one SQLite file ([ADR-0008](../adr/0008-one-process-on-sqlite-with-hand-written-migrations.md)), with one Analysis Run in flight and one writer at a time. No latency, throughput, availability or recovery target is set or measured, and no scenario above implies one.

The limits that do exist are functional guards, not capacity targets:
- A second Analysis Run is refused with `409` while one is in flight.
- The Assistant's usage limits answer `429` when a user goes over them.

The risks this non-goal carries are [R-04](11-risks-and-technical-debt.md#r-04) to [R-06](11-risks-and-technical-debt.md#r-06). The [Target / Production Roadmap](13-roadmap.md) sets targets and lifts the single-process design.
