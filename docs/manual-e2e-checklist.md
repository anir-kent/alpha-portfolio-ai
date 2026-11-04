# Manual E2E checklist (one page)

Detail for each step: `docs/manual-e2e-guide.md`. Tick as you go.

## Setup
- [x] `source .venv/bin/activate`
- [ ] `uv run python -m app.seeder` and `uv run python -m app.research_seed`
- [ ] `uv run uvicorn app.main:create_app --factory --port 8000`
- [x] `cd frontend && npm run dev` -> http://localhost:5173
- [x] Log in with username = role name (`advisor`, `compliance_officer`, ...) and the `APP_SEED_USER_PASSWORD` password
- [x] LLM mode known: live (AI steps work) or recorded (AI steps show "failed", rest still works)

## Advisor: queue (C001-C005 are the planted scenarios)
- [x] Nav shows no Audit, Governance or Config
- [x] Run analysis; all 25 portfolios scored
- [x] Score 0-100, High/Medium/Low label, 4-part breakdown, SLA flag, cited narrative
- [x] Filter by label and risk profile; sort by review-due
- [x] C001-C004 rank above C005; C005 is Low

## Advisor: drill-down and recommendation (C001)
- [x] Holdings, actual vs target, drift vs tolerance bands, one Portfolio Drift number
- [x] Risk profile, horizon, liquidity, restrictions shown
- [x] Look-through sector exposure includes tech held via ETFs
- [ ] Insights with report-page citations
- [ ] Proposed vs allowed Research Tilt (+-2 pp)
- [ ] Trade Lines in % and currency
- [ ] Rationale cited; ungrounded claims flagged and kept out of the memo; memo present
- [ ] Suitability results show rule ID and numbers
- [ ] "Approved = cleared to act outside this system" is clear
- [ ] `relationship_manager` sees masked client fields; `advisor` sees them

## Approvals
- [ ] C002/C003 (no breach, not high-impact): Advisor accept -> Approved
- [ ] Modify Trade Lines -> new linked version, suitability re-run, breach warning shown
- [ ] C004: Advisor accept -> Pending Compliance
- [ ] Compliance sees rule ID, limit, actual, Trade Line, warnings, restrictions, grounding flags
- [ ] Compliance approve without rationale is refused; with rationale works; block works
- [ ] Compliance cannot act before the Advisor has decided
- [ ] High-impact (turnover >= 15% or line >= 10%) reaches Investment Committee with thresholds visible
- [ ] Committee approve/reject needs a rationale

## RBAC
- [ ] Advisor opening `/audit` or `/governance` gets no view
- [ ] Forbidden API calls return 403 (e.g. `GET /api/config` as `relationship_manager`, `POST /api/analysis/runs` as `auditor`)

## Auditor
- [ ] Audit search by type, actor, client, date; `access_denied` events present
- [ ] Overrides highlighted; AI events show model and prompt version; seed items show human-verified
- [ ] Lineage: report passage -> insight -> tilt -> recommendation -> decisions
- [ ] Verify chain reports OK
- [ ] Governance: model card, prompt log, AI quality panel
- [ ] Adversarial fixtures (fabricated quote, wrong number, uncited call) flagged or blocked

## Supersession and clean portfolio
- [ ] Rerun analysis: open recommendations become Superseded
- [ ] C005 still produces no action

## API-only roles (curl or http://localhost:8000/docs)
- [ ] `research_analyst`: upload report; insights pending; approve via `/api/insights/{id}/decision`
- [ ] `platform_owner`: `GET /api/health`; `PATCH /api/config` changes the next run
- [ ] `portfolio_manager`: read-only

## Optional
- [ ] Tamper with a copy of `data/app.db`; Verify chain names the first broken link

## Notes
- Live mode costs money and the first run is slower (one LLM call per portfolio narrative)
- Config and Health nav items hit the placeholder page (no routes in `main.tsx`)
- README says Anthropic is the default provider; confirm `.env` is intentional
