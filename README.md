# Portfolio Rebalancing

An advisor-assist platform for wealth management. It ingests research Reports, extracts cited Insights, and monitors synthetic Client Portfolios against their Target Allocations. A deterministic engine computes drift, a priority score and the Suitability Rule outcomes. A GenAI layer interprets the research, proposes a bounded Research Tilt and writes the rationale, the advisor memo and a "why this client, why now" narrative, and a grounding validator holds it to its citations. Humans decide through a tiered workflow (Advisor always, Compliance on a breach, Investment Committee when high-impact), and every step lands in one hash-chained audit trail. **Nothing is ever executed:** Approved means cleared to act on outside this system.

Vocabulary: `GLOSSARY.md`. Decisions: `docs/adr/`. Spec: `.scratch/ai-portfolio-rebalancing/spec.md`. Coding standards and checks: `CODING_STANDARDS.md`.

## Data stance

**Market data is real; Clients are synthetic** (ADR-0003). No real client data is used anywhere.

- **Market data snapshot** (`data/market_snapshot.json`, committed). About 30 real Instruments from Twelve Data: 13 equities, 11 sector ETFs covering the 11 GICS sectors, SPY, 4 bond ETFs and a cash proxy (SGOV). The committed snapshot was fetched on 2026-11-03 (prices as of the 2026-11-02 close, with 30 daily closes of history each). The app reads only this file, so it runs fully offline. The refresh script is the only code that uses the network.
- **Fund look-through** (`data/fund_lookthrough.json`, hand-built). Sector weights for every fund and ETF, because the free tier provides none. Sector ETFs are 100% their sector, bond funds are `Fixed Income` and the cash proxy is `Cash`.
- **Synthetic Clients** (`app.seeder`). 25 generated Clients across four Risk Profiles, with taxable and tax-advantaged accounts. Generation is deterministic: the same seed and snapshot give identical Clients, Accounts, Holdings, Target Allocations and Restrictions. Review-due dates are relative to the snapshot date. Names and emails are invented (`*.example.invalid`).
- **Research** (`app.research_seed`). Five sample Reports (the two provided PDFs plus three synthetic house views), the hand-transcribed p3 scorecard of the Q2 research update (`data/seed/q2_scorecard_p3.json`) and sample Insights. No LLM is involved: every seeded Insight is approved as human-verified, and the audit trail records that (actor `seed`, `human_verified: true`).
- **LLM replies** (`tests/fixtures/llm`, committed). Recordings of real model replies made against the seeded data, so the demo and the tests replay them with no network or cost (see LLM modes below).

### Planted scenarios

These are fixed by the seed and the committed snapshot. Tests and the walkthrough assert them.

| Client | Scenario | What the first Analysis Run produces |
| --- | --- | --- |
| C001 | Heavy tech | Sector concentration breach (SR-03) through look-through; drift in band, so no Recommendation |
| C002 | Overweight energy | A Recommendation still in breach after trading, so the Advisor's accept needs Compliance. With the committed recordings, its Research Tilt also takes turnover to 16%, so it needs the Investment Committee as well |
| C003 | Cash drag | A clean but high-impact Recommendation (turnover 25%), so it needs the Investment Committee |
| C004 | Holds restricted XOM | Client Restrictions breach (SR-05) on what is held; drift in band, so no Recommendation |
| C005 | Clean | No breach, no drift and no Recommendation: the system does not over-recommend |

## Setup

You need Python 3.13 with [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
uv sync                                 # backend dependencies into .venv
source .venv/bin/activate
cp .env.example .env                    # then set APP_SEED_USER_PASSWORD (and the keys below, if you need them)
(cd frontend && npm ci && npm run gen:api)   # frontend dependencies and the typed API client
uv run pre-commit install               # optional: the lint, format and type checks on each commit
```

Every setting is an `APP_*` variable, read from the environment or the git-ignored `.env` (`app/settings.py`). A variable exported in your shell outranks `.env`, so check `env | grep ^APP_` when a setting seems ignored. Secrets are never committed. Only two features need a key: `APP_TWELVE_DATA_API_KEY` for the market-data refresh, and `APP_LLM_API_KEY` for live LLM mode.

## Seed and run

A fresh seed starts from an empty database:

```bash
rm -f data/app.db                       # fresh start (the database is created on first use)
uv run python -m app.seeder             # 25 synthetic Clients; --seed N for another deterministic set
uv run python -m app.research_seed      # 5 Reports and the human-verified Insights; idempotent
```

Then start the API and the UI in two terminals:

```bash
APP_LLM_MODE=recorded APP_LLM_RECORDINGS_DIR=tests/fixtures/llm uv run uvicorn app.main:create_app --factory --port 8000
cd frontend && npm run dev              # http://localhost:5173, which proxies /api to port 8000
```

- Log in with any role name as the username (`advisor`, `relationship_manager`, `compliance_officer`, `investment_committee`, `auditor`, `research_analyst`, `platform_owner`, `portfolio_manager`). The password for every role is `APP_SEED_USER_PASSWORD`.
- As `advisor`, start an Analysis Run from the Queue. You can also start one with `uv run python -m app.analysis` or `POST /api/analysis/runs`. The OpenAPI docs are at <http://localhost:8000/docs>.
- In recorded mode with `APP_LLM_RECORDINGS_DIR=tests/fixtures/llm` and the default `APP_LLM_MODEL` and `APP_LLM_BASE_URL` (an exported value overrides the default: unset it), the Analysis Run's AI steps and the Assistant's Suggested Questions replay the committed recordings. That only works on a fresh seed and for the first Analysis Run, because recordings replay byte-identical prompts only. Anything else is reported as a failed AI step, and the deterministic results still stand.

## Demo walkthrough

**Scripted:** `uv run python -m scripts.walkthrough`. It plays the planted scenarios from the Queue to the Auditor's evidence through the HTTP API. It runs on a fresh throwaway database (never `data/app.db`) in recorded mode, printing each claim with its evidence, and exits non-zero if any claim fails. The acts:

1. Queue: ranking, the four-part score breakdown, labels, the SLA flag, cited narratives, filter and sort.
2. Drill-down: look-through, sector concentration and Restriction breaches, approved research, RM masking.
3. Recommendation: Trade Lines, post-trade Suitability, the bounded Research Tilt, the grounded memo.
4. A single-approver accept, the Compliance exception on C002 and a Compliance block. The single-approver and block cases are picked by approval route: C017 and C009 on the committed recordings.
5. Modify C003 into a breach, then Compliance and the Investment Committee in order.
6. Access denied.
7. Auditor evidence: lineage, overrides, the human-verified marker, chain verification, governance, adversarial fixtures.
8. Supersession and the clean Portfolio.

`tests/test_walkthrough.py` runs it on every test run.

**In the browser:** `docs/manual-e2e-guide.md` tells the same story role by role, with a tick list in `docs/manual-e2e-checklist.md`.

## Working UI roles

Navigation follows each role's permissions, and the server enforces every action.

- **Advisor** and **Relationship Manager**: Queue, Portfolio drill-down (with the approved research on what it holds) and Recommendations. The Relationship Manager sees Client fields masked.
- **Compliance Officer**: Approvals and LLM Exchanges. **Investment Committee**: Approvals.
- **Research Analyst**: the Research screen. It opens on To review (every Insight awaiting review, grouped by Report), with Upload Report and the Reports library. Each Insight is approved or rejected beside its cited page, by mouse or keyboard. Only approved Insights reach the Advisor.
- **Auditor**: Audit, Lineage, Governance and LLM Exchanges.
- **Platform Owner**: Governance, LLM Exchanges, Config and Health. It changes configuration through the API (`PATCH /api/config`, see `/docs`). **Portfolio Manager**: Config (read-only), and Portfolios and drift through the API.
- **Config** and **Health** (for the roles that can read them) are read-only screens of `GET /api/config` and `GET /api/health`; changes go through `PATCH /api/config`.
- Each role opens on its first screen.
- Every role has the Assistant, which answers questions about the screen in view.

## Refresh market data

```bash
APP_TWELVE_DATA_API_KEY=<free key> uv run python -m app.market_refresh
```

The refresh respects the free tier (8 symbols per minute, so it takes about 4 minutes) and leaves the existing snapshot untouched if any symbol fails. A refreshed snapshot changes the seeded Holdings' values and every prompt built from them. After refreshing, re-record the LLM replies (below) and check the planted scenarios still hold (`uv run pytest`).

## LLM modes and recordings

`app/llm.py` is the single OpenAI-compatible interface. Prompts live in `app/prompts.py` and are versioned, and every call logs its model and prompt version to the audit chain. Every call is also stored as an LLM Exchange (ADR-0004).

- `APP_LLM_MODE=recorded` (the default; tests and demos) replays recordings from `APP_LLM_RECORDINGS_DIR` with no network. A missing recording is an error, never a guess.
- `APP_LLM_MODE=live` calls `APP_LLM_BASE_URL` with `APP_LLM_MODEL`. The default is OpenRouter (`https://openrouter.ai/api/v1/`, `anthropic/claude-sonnet-5.5`), so another model is a config change. Through OpenRouter, calls are routed only to providers that support every parameter sent, so the reply's JSON schema is always enforced. `APP_LLM_TEMPERATURE` is sent only when set: Claude 5 models accept none, and through OpenRouter a request carrying one finds no endpoint. The governance model card reports what is sent. `APP_LLM_RECORD=true` saves each live reply as a recording.
- **Re-recording the demo** (`uv run python -m tests.fixtures.suggested_questions`) needs `APP_LLM_API_KEY`, `APP_LLM_BASE_URL` and `APP_LLM_MODEL` set to the recorded endpoint and model. It records, against a fresh seed:
  - the first Analysis Run's narratives, tilts, rationale and memos;
  - every Assistant Suggested Question on the demo screens;
  - the calls the walkthrough adds.

  It removes recordings nothing uses any more. Re-record after changing a prompt, a Screen Context builder, the platform brief, the seed, the snapshot or the walkthrough. Audit screens never replay, because their events carry wall-clock timestamps.
- Live smoke test: `LLM_LIVE=1 APP_LLM_API_KEY=... uv run pytest tests/test_research.py -k live`.

## Tests and checks

```bash
uv run pytest                           # the whole suite, offline, on recorded LLM replies
uv run ruff check && uv run ruff format --check && uv run mypy
cd frontend && npm run lint && npm run format:check && npm run typecheck
```

The suite tests behaviour at two seams (spec, Testing Decisions):

- **The HTTP API**, on seeded synthetic data and the committed snapshot. It covers:
  - the Queue and drift;
  - every Suitability Rule;
  - the Recommendation lifecycle and the tiered approvals, including the invariant that no Recommendation reaches Approved without a human Decision at every required step (`tests/test_approvals.py`);
  - RBAC and masking;
  - the audit chain and lineage;
  - the end-to-end walkthrough.
- **The LLM interface**, the only test double. It includes the grounding fixtures: a fabricated quote, a wrong number and an uncited asset call must each be flagged (`tests/test_grounding.py`, `tests/test_governance.py`).

CI (`.github/workflows/ci.yml`) runs every check on each push and pull request.

## Scoring reference

`GET /api/queue` returns the current Analysis Run. It filters by `label`, `risk_profile`, `review_due_from/to` and `sla_breached`, and sorts by `sort`/`order`.

The score (0-100) is a weighted sum of four components, each normalised to 0-100:

- **drift:** Portfolio Drift, full at 10 pp.
- **risk:** the worst Asset-Class Drift, as a share of the Risk Profile's breach threshold.
- **opportunity:** look-through exposure to sectors with an approved Insight.
- **urgency:** days past review-due, as a share of the SLA.

The labels are High >= 70, Medium >= 40, else Low. Weights, Tolerance Bands, tilt bounds, `sla_days` and the approval thresholds come from `/api/config`. Days are measured at the market snapshot date.
