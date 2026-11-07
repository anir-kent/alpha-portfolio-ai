# Portfolio Rebalancing

Advisor-assist platform; it never executes trades. Vocabulary: `GLOSSARY.md`. Decisions: `docs/adr/`.

## Working UI roles

`cd frontend && npm run dev` serves the UI at <http://localhost:5173>; the username is the role name. Navigation follows each role's permissions, and the server enforces every action. The Config and Health nav items, shown to roles that can read them, still lead to a placeholder.

- **Advisor** and **Relationship Manager**: Queue, Portfolio drill-down (with the approved research on what it holds) and Recommendations. The Relationship Manager sees client fields masked.
- **Compliance Officer**: Approvals and LLM Exchanges. **Investment Committee**: Approvals.
- **Research Analyst**: the Research screen. It opens on To review (every Insight awaiting review, grouped by Report), with Upload Report and the Reports library; each Insight is approved or rejected beside its cited page, by mouse or keyboard. Only approved Insights reach the Advisor.
- **Auditor**: Audit, Lineage, Governance and LLM Exchanges.
- **Platform Owner**: Governance and LLM Exchanges; config and health are API only (`/docs`). **Portfolio Manager**: API only (its only nav item is the Config placeholder).

Walkthrough: `docs/manual-e2e-guide.md`, with the tick list in `docs/manual-e2e-checklist.md`.

## Data stance

**Market data is real; Clients are synthetic** (ADR-0003). No real client data is used anywhere.

- **Market data snapshot** (`data/market_snapshot.json`, committed). ~30 Instruments: 13 equities and 11 sector ETFs covering the 11 GICS sectors, SPY, 4 bond ETFs and a cash proxy (SGOV). The app reads it through `app.market_data.MarketData` and runs fully offline; the refresh script is the only code that uses the network.
  - Refresh: `APP_TWELVE_DATA_API_KEY=<free key> uv run python -m app.market_refresh`. Respects the free tier (8 symbols per minute, so it takes about 4 minutes) and leaves the existing snapshot untouched if any symbol fails.
  - The committed snapshot was fetched from Twelve Data on 2026-11-03 (prices as of the 2026-11-02 close, 30 daily closes of history each). The key is read from `APP_TWELVE_DATA_API_KEY` (env or the git-ignored `.env`); never commit it.
- **Fund look-through** (`data/fund_lookthrough.json`, hand-built). Sector weights for every fund and ETF, because the free tier provides none. Sector ETFs are 100% their sector, bond funds are `Fixed Income`, the cash proxy is `Cash`.
- **Synthetic Clients** (`uv run python -m app.seeder [--seed N]`). Deterministic: the same seed and snapshot give identical Clients, Accounts, Holdings, Target Allocations and Restrictions. Re-running replaces all Client data. Generates 25 Clients across four Risk Profiles with taxable and tax-advantaged accounts. Planted scenarios have fixed IDs: `C001` heavy tech, `C002` overweight energy, `C003` cash drag, `C004` restricted-instrument breach (holds XOM, restricted), `C005` clean Portfolio. Review-due dates are relative to the snapshot date.
- **Research seeds** (`uv run python -m app.research_seed`). Idempotent. Loads five sample Reports (the two provided PDFs plus three synthetic house views), the hand-transcribed p3 scorecard of the Q2 research update (`data/seed/q2_scorecard_p3.json`) and sample Insights. No LLM is involved: every seeded Insight is approved as human-verified, and the audit trail records that (actor `seed`, `human_verified: true`).
- **LLM interface** (`app/llm.py`). One OpenAI-compatible interface. `APP_LLM_MODE=recorded` (default; tests and demos) replays responses from `APP_LLM_RECORDINGS_DIR` with no network. `APP_LLM_MODE=live` calls `APP_LLM_BASE_URL` (Anthropic's compatibility endpoint by default; a LiteLLM gateway later) with `APP_LLM_MODEL`; `APP_LLM_RECORD=true` saves each live reply as a recording. Prompts live in `app/prompts.py` and are versioned; every call logs model and prompt version to the audit chain. Live smoke test: `LLM_LIVE=1 APP_LLM_API_KEY=... uv run pytest tests/test_research.py -k live`. **Assistant Suggested Questions** replay from committed recordings in `tests/fixtures/llm`, made against the seeded data (Clients, research seeds, one Analysis Run) with `uv run python -m tests.fixtures.suggested_questions`. Re-record after changing a Screen Context builder, the platform brief, the Assistant prompt or the seeded data. In recorded mode any other Question is told that only Suggested Questions work in replay mode, and Audit screens never replay, since their events carry wall-clock timestamps.
- **Drift and priority queue** (`uv run python -m app.analysis`, or `POST /api/analysis/runs`). Scores every Portfolio and supersedes the earlier run; `GET /api/queue` returns the current run, filterable by `label`, `risk_profile`, `review_due_from/to`, `sla_breached` and sortable by `sort`/`order`. Score (0-100) = weighted sum of four components, each normalised to 0-100: drift (Portfolio Drift, full at 10 pp), risk (worst Asset-Class Drift as a share of the Risk Profile's breach threshold), opportunity (0 until Insights exist), urgency (days past review-due as a share of the SLA). Weights, Tolerance Bands and `sla_days` come from `/api/config`. High >= 70, Medium >= 40, else Low. The SLA is breached once days past review-due reach `sla_days`. Days are measured at the market snapshot date. Advisor and Relationship Manager roles only.
