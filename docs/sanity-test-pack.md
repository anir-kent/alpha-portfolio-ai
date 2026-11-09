# Sanity test pack: pydantic-ai LLM layer and the agentic Assistant

A short browser pass over every change in `.scratch/pydantic-ai-agentic-assistant/` (ADR-0010). It is not exhaustive; the full list is `docs/manual-e2e-checklist.md`.

Recorded mode replays only Suggested Questions, so Parts A and B run offline. Part C (least privilege, self-correction, budget) needs live mode through OpenRouter.

## 0. Setup (recorded mode, fresh seed)

```bash
source .venv/bin/activate
rm -f data/app.db
uv run python -m app.seeder
uv run python -m app.research_seed
APP_LLM_MODE=recorded APP_LLM_RECORDINGS_DIR=tests/fixtures/llm \
  uv run uvicorn app.main:create_app --factory --port 8000      # terminal 1
cd frontend && npm run dev                                       # terminal 2 -> http://localhost:5173
```

- **Logins:** the username is the role name (`advisor`, `auditor`, `platform_owner`, `research_analyst`). The password is your `APP_SEED_USER_PASSWORD`.
- **Browsers:** use one incognito window per role, or log out between roles.
- **Fresh seed:** recordings only match a fresh seed and the **first** Analysis Run. If anything replays as "failed" unexpectedly, reset the seed before suspecting the code.

## Part A: Stage 1, no regression in the pipeline steps (recorded)

| # | Role | Steps | Expected |
|---|---|---|---|
| **1** | advisor | `/queue` → **Run analysis** | The modal runs Load inputs → Score Portfolios (25/25) → Record run → Priority narratives → Recommendation narratives, and every step ends **done**. The Queue shows scores and cited narratives, and C001-C004 rank above C005. |
| **2** | advisor | Open the C003 Recommendation → AI contribution | Research Tilt and Rationale/memo each show a **recorded** pill, `ok`, and latency "n/a (replayed)". No prompt text is visible to the advisor. |
| **3** | auditor | `/llm-exchanges` | The pipeline Exchanges from the run are listed as **single rows with no step marker**, one Exchange per step. |
| **4** | research_analyst | `/research` → **Upload Report** → `tests/fixtures/house_view_demo.txt` | "Extracting Insights…", then the Report opens with **3 Insights awaiting review** (IT, Utilities, equity). There's no 500 and no hang. This checks that the async upload route no longer calls `run_sync` inside the event loop. |
| **4b** | research_analyst | Upload any other new `.txt` | The upload succeeds, then shows "Extraction failed: No recorded response…" with **Upload again**. The failure is handled, not a crash. |

## Part B: Stage 2, agentic Assistant (recorded)

| # | Role | Steps | Expected |
|---|---|---|---|
| **5** | advisor | On `/queue`, open the Assistant and click the Suggested Question **"What are the holdings and drift of Portfolio C001?"** | The Answer lists C001's holdings and drift, which are not on the Queue screen. The Claim chips cite `portfolio.C001.*` and are marked grounded. |
| **6** | advisor | Expand **"How I answered"** on that Answer | It starts collapsed. Open, it shows: model request 1 → `look_up_portfolio` (`portfolio_id: C001`) with a holdings/drift summary → model request 2, then **"Requests: 2 / 6"** and the input/output tokens. **Reload the page**: the summary is still there. |
| **7** | advisor | On `/portfolios/C001`, click **"Which asset class drives this Portfolio's drift?"**, then expand "How I answered" | A **one-step** Trajectory: a single model request, no lookups, and usage shown. Single-step and multi-step Answers render the same way. |
| **8** | advisor | Type **"Should I buy NVDA?"**, then type **"What colour is the sky?"** | First: the fixed Out-of-Scope refusal. Second: **"Only Suggested Questions work in replay mode."** with Retry. A replay miss must not return a guessed reply. |
| **9** | auditor | `/llm-exchanges` → find the test 5 Answer → open step 2 → `/audit` → **Verify chain** | The Answer shows as **one row, "▸ 2 steps"**, with summed tokens. It expands to step 1/2 and step 2/2. The step 2 drawer reads "Step 2 of 2 in this Trajectory", and Prompt → Request messages shows the step 1 **tool call and tool result verbatim**. Previous and Next work. The `assistant.answered` event's `exchanges` lists both Exchanges by id and hash, in order. Verify chain reports **OK**. |
| **9b** | platform_owner | `/governance` | Capture health shows **Trajectories** and **Turns using lookups**. The Assistant panel shows `assistant_answer@v5` and "Model requests per Answer: 6". |

## Part C: agentic guardrails (live mode, OpenRouter)

Restart the API with `APP_LLM_MODE=live`. Recorded data no longer matters here.

| # | Role | Steps | Expected |
|---|---|---|---|
| **10** | advisor | On `/queue`, ask **"What is waiting for a Compliance Decision right now?"** | "How I answered" shows `look_up_approvals` → **"not found or not permitted for your role"**. The Answer says plainly that the advisor can't see it, without guessing. |
| **11** | advisor | On `/portfolios/C001`, ask **"Quote the exact cash weight to two decimals and the drift of every Asset Class."** | If the first draft gets a figure wrong, "How I answered" shows **"Self-correction · N grounding issues sent back"** between the two model requests. Any Claim still wrong after the one retry is **flagged red**, not hidden. As auditor, Exchange 2 of that Trajectory carries the failing Claims verbatim. *Whether a retry happens depends on the model, so a clean first draft also passes. Ask again if you want to see a retry.* |
| **12** | advisor | Restart with `APP_ASSISTANT_REQUEST_LIMIT=2`. On `/queue`, ask **"Compare the holdings and drift of Portfolios C001, C002 and C003."** | The turn fails with **"That Question needed more lookups than one Answer may make. Try a narrower Question."**, plus Retry and **"Requests: 2 / 2"**. As auditor: `assistant.failed` has `reason: budget_exhausted`, both Exchanges are anchored, and Verify chain is still **OK**. |

## Pass criteria

- Tests **1-9b** must all pass. They are deterministic, so any failure is a bug, or a stale seed.
- Tests **10-12** depend on the model's behaviour, apart from these hard checks:
  - the "not permitted" lookup result
  - the budget message and `budget_exhausted`
  - Verify chain staying OK

**Where to look first:**

- Test 4 fails → check the report-upload route (ticket 01).
- Test 9 fails on the chain or `exchanges` order → check the trajectory anchoring and verification code (tickets 02 and 11).
