# Sanity test pack: the LLM Graphs and the agentic Assistant

A short browser pass over the LLM layer: the pipeline graph (`START → generate → END`) and the Assistant graph (`agent`, `tools`, `validate`, `budget_exhausted`; ADR-0010 and ADR-0011). It is not exhaustive; the full list is `docs/manual-e2e-checklist.md`.

Every call is live, so the whole pack needs `APP_LLM_API_KEY` (OpenRouter by default). Model wording varies, so each row checks structure and guardrails, not exact text.

## 0. Setup (fresh seed, live)

```bash
source .venv/bin/activate
rm -f data/app.db
uv run python -m app.seeder
uv run python -m app.research_seed
uv run uvicorn app.main:create_app --factory --port 8000       # terminal 1 (APP_LLM_API_KEY in .env)
cd frontend && npm run dev                                       # terminal 2 -> http://localhost:5173
```

- **Logins:** the username is the role name (`advisor`, `auditor`, `platform_owner`, `research_analyst`). The password is your `APP_SEED_USER_PASSWORD`.
- **Browsers:** use one incognito window per role, or log out between roles.
- **Fresh seed:** start from a fresh seed so the planted scenarios are as documented. If an AI step shows "failed" unexpectedly, check the key and the endpoint before suspecting the code.

## Part A: the pipeline graph

| # | Role | Steps | Expected |
|---|---|---|---|
| **1** | advisor | `/queue` → **Run analysis** | The modal runs Load inputs → Score Portfolios (25/25) → Record run → Priority narratives → Recommendation narratives, and every step ends **done**. The Queue shows scores and cited narratives, and C001-C004 rank above C005. |
| **2** | advisor | Open the C003 Recommendation → AI contribution | Research Tilt and Rationale/memo each show `ok` and a measured latency in ms. No prompt text is visible to the advisor. |
| **3** | auditor | `/llm-exchanges` | The pipeline Exchanges from the run are listed as **single rows with no step marker**, one Exchange per step. |
| **4** | research_analyst | `/research` → **Upload Report** → `tests/fixtures/house_view_demo.txt` | "Extracting Insights…", then the Report opens with its Insights awaiting review (expect IT, Utilities and equity). There's no 500 and no hang. This checks that the async upload route no longer calls `run_sync` inside the event loop. |
| **4b** | research_analyst | Restart the API without `APP_LLM_API_KEY`, then upload any new `.txt` | The upload succeeds, then shows "Extraction failed: …" with **Upload again**. The failure is handled, not a crash. |

## Part B: the Assistant graph

| # | Role | Steps | Expected |
|---|---|---|---|
| **5** | advisor | On `/queue`, open the Assistant and click the Suggested Question **"What are the holdings and drift of Portfolio C001?"** | The Answer lists C001's holdings and drift, which are not on the Queue screen (the `agent` → `tools` → `agent` edges). The Claim chips cite `portfolio.C001.*` and are marked grounded. |
| **6** | advisor | Expand **"How I answered"** on that Answer | It starts collapsed. Open, it shows: model request 1 → `look_up_portfolio` (`portfolio_id: C001`) with a holdings/drift summary → model request 2, then **"Requests: 2 / 6"** and the input/output tokens. **Reload the page**: the summary is still there. |
| **7** | advisor | On `/portfolios/C001`, click **"Which asset class drives this Portfolio's drift?"**, then expand "How I answered" | A **one-step** Trajectory: a single model request, no lookups, and usage shown. Single-step and multi-step Answers render the same way. |
| **8** | advisor | Type **"Should I buy NVDA?"**, then type **"What colour is the sky?"** | First: the fixed Out-of-Scope refusal. Second: a short, in-scope-only reply or the same refusal; it never gives an unrelated answer. |
| **9** | auditor | `/llm-exchanges` → find the test 5 Answer → open step 2 → `/audit` → **Verify chain** | The Answer shows as **one row, "▸ 2 steps"**, with summed tokens. It expands to step 1/2 and step 2/2. The step 2 drawer reads "Step 2 of 2 in this Trajectory", and Prompt → Request messages shows the step 1 **tool call and tool result verbatim**. Previous and Next work. The `assistant.answered` event's `exchanges` lists both Exchanges by id and hash, in order. Verify chain reports **OK**. |
| **9b** | platform_owner | `/governance` | Capture health shows **Trajectories** and **Turns using lookups**. The Assistant panel shows `assistant_answer@v5` and "Model requests per Answer: 6". |

## Part C: agentic guardrails

| # | Role | Steps | Expected |
|---|---|---|---|
| **10** | advisor | On `/queue`, ask **"What is waiting for a Compliance Decision right now?"** | "How I answered" shows `look_up_approvals` → **"not found or not permitted for your role"**. The Answer says plainly that the advisor can't see it, without guessing. |
| **11** | advisor | On `/portfolios/C001`, ask **"Quote the exact cash weight to two decimals and the drift of every Asset Class."** | If the first draft gets a figure wrong, "How I answered" shows **"Self-correction · N grounding issues sent back"** between the two model requests. Any Claim still wrong after the one retry is **flagged red**, not hidden. As auditor, Exchange 2 of that Trajectory carries the failing Claims verbatim. *Whether a retry happens depends on the model, so a clean first draft also passes. Ask again if you want to see a retry.* |
| **12** | advisor | Restart with `APP_ASSISTANT_REQUEST_LIMIT=2`. On `/queue`, ask **"Compare the holdings and drift of Portfolios C001, C002 and C003."** | The turn fails with **"That Question needed more lookups than one Answer may make. Try a narrower Question."**, plus Retry and **"Requests: 2 / 2"**. As auditor: `assistant.failed` has `reason: budget_exhausted`, both Exchanges are anchored, and Verify chain is still **OK**. |

## Pass criteria

- Tests **1-9b** must all pass. Their structure is deterministic, so a failure is a bug, a bad key or a stale seed.
- Tests **10-12** depend on the model's behaviour, apart from these hard checks:
  - the "not permitted" lookup result
  - the budget message and `budget_exhausted`
  - Verify chain staying OK

**Where to look first:**

- Test 4 fails → check the report-upload route (ticket 01).
- Test 9 fails on the chain or `exchanges` order → check the trajectory anchoring and verification code (tickets 02 and 11).
