# 11: Exchanges page and Governance show Trajectories

**What to build:** An Auditor reviews a multi-step Answer as one unit. The LLM Exchanges list groups rows by Trajectory (a Trajectory of one looks like today's row). The Exchange drawer shows "step k of n" with previous and next navigation through the Trajectory. Governance capture health adds a Trajectory count and the share of Assistant turns that used lookups. Still `llm:read` only, per ADR-0004. Spec: "Assistant turn API and UI".

**Blocked by:** 07 (Assistant tracer bullet: one lookup, end to end)

**Status:** resolved

- [x] The Exchanges list API can return Exchanges grouped or filtered by Trajectory, with the existing filters still working
- [x] The Exchanges page renders a multi-step Trajectory as one expandable group in position order
- [x] The drawer shows the Trajectory position and lets the Auditor step to neighbours. Tool calls and results are visible verbatim in each next request's prompt
- [x] Governance capture health shows the Trajectory count and the share of Assistant turns that used lookups
- [x] Advisors still see no raw Exchanges. Permission tests are extended
- [x] API tests cover grouping. UI behaviour follows existing drawer tests, or is added to the manual E2E checklist
