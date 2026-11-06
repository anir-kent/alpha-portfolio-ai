# 05: Interrupted runs: a server restart never blocks the next Analysis Run

**What to build:** If the API process dies mid-run, the run's scoring never commits and its in-memory progress is lost. On the next startup, any Analysis Run row without an outcome is marked **Interrupted**. A user who reopens it (from a stale tab or by id) sees "Run interrupted. The Queue still shows the previous run". A new run can start straight away. See the spec at `.scratch/run-analysis-progress/spec.md` and ADR-0005.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] At app startup, every Analysis Run row without an outcome gets `interrupted` and a finish time, and its Run Step results show the steps that never finished as not done
- [ ] API test: an outcome-less row plus an app restart gives `GET /analysis/runs/{id}` returning `interrupted`, `current` returning `204`, and a new start returning `202`
- [ ] The Queue still serves the latest completed run
- [ ] The modal shows the Interrupted state with the agreed wording and refreshes nothing
- [ ] `npm run typecheck` passes; the manual E2E checklist gains an item for stopping the API mid-run and restarting it
