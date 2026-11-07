# End-to-end manual check: step-by-step guide

Browser walkthrough of the main functionality against the planted synthetic scenarios. Requirements: `specs/AI_Portfolio_Rebalancing_Use_Case_Requirements_and_Scope.md` and `.scratch/ai-portfolio-rebalancing/spec.md`. A one-page tick list is in `docs/manual-e2e-checklist.md`.

The same story runs headless as `uv run python -m scripts.walkthrough`, which checks every claim through the API on a fresh seed. Run it first: if it passes, any difference you see in the browser is a UI problem.

Button labels below are taken from the code, not from a live run, and may differ slightly on screen.

## 0. Before you start

**LLM mode.** The repo ships recordings, made against `anthropic/claude-sonnet-5.5` through OpenRouter, for:

- the first Analysis Run on a fresh seed (queue narratives, Research Tilts, rationale and memos);
- the Assistant's Suggested Questions;
- the demo house view's extraction.

To replay them:

- Start the API with `APP_LLM_MODE=recorded APP_LLM_RECORDINGS_DIR=tests/fixtures/llm`, and keep the default model settings.
- Replay only works from a fresh seed, for the first Analysis Run. Recordings replay byte-identical prompts only.
- Anything not recorded (a second run, a Report you upload, a Question you type) shows as a failed AI step with a short reason, and latency reads "n/a (replayed)". The deterministic parts (drift, suitability, approvals, audit) must still work, so a failed AI step is itself a useful check.

For fresh AI output, use live mode instead (`APP_LLM_MODE=live` with your `APP_LLM_API_KEY`).

**Reset and start** (two terminals, from the repo root):

```bash
source .venv/bin/activate
rm -f data/app.db                      # fresh seed, so the recordings replay
uv run python -m app.seeder            # 25 synthetic clients, deterministic
uv run python -m app.research_seed     # 5 reports + human-verified approved insights
APP_LLM_MODE=recorded APP_LLM_RECORDINGS_DIR=tests/fixtures/llm \
  uv run uvicorn app.main:create_app --factory --port 8000   # Terminal 1
cd frontend && npm run dev                                  # Terminal 2 -> http://localhost:5173
```

- The Vite dev server proxies `/api` to port 8000.
- All users log in with the password in `APP_SEED_USER_PASSWORD` (`aditya@123` in `.env.example`; check your `.env`).
- **The username is the role name:** `advisor`, `relationship_manager`, `compliance_officer`, `investment_committee`, `auditor`, `platform_owner`, `research_analyst`, `portfolio_manager`.
- Use a separate browser profile or incognito window per role, since the session cookie is shared per origin. Alternatively, log out between roles.

## Planted scenarios

| Client | Scenario                       | What to expect                                  |
| ------ | ------------------------------ | ----------------------------------------------- |
| C001   | Heavy tech                     | SR-03 sector concentration breach through look-through; drift in band, so no Recommendation |
| C002   | Overweight energy              | A Recommendation still in breach after trading, so it needs Compliance |
| C003   | Cash drag                      | A clean but high-impact Recommendation (turnover 25%), so it needs the Investment Committee |
| C004   | Holds XOM, which is restricted | SR-05 Client Restrictions breach on the holding; drift in band, so no Recommendation |
| C005   | Clean portfolio                | No action, so the system doesn't over-recommend |

Two non-planted Clients complete the set: **C017** has a Recommendation that needs the Advisor only, and **C009** has a breach that Compliance can block.

## Act 1: Advisor builds the queue (stories 1-6, 66-68)

1. Log in as `advisor`. You land on the Queue. The nav shows no Audit, Governance or Config items.
2. On **Queue**, start an analysis run (the on-demand button). It scores all 25 portfolios.
3. Check each row for:
   - a score from 0 to 100 and a High/Medium/Low label (High >= 70, Medium >= 40);
   - a four-part breakdown of drift, risk, opportunity and urgency;
   - a cited "why now" narrative (or a "failed" status if the LLM is unavailable);
   - an SLA-breached flag.
4. Filter by label and by risk profile, and sort by review-due date.
5. Confirm C001-C004 rank above C005, and that C005 sits at Low. C003 tops the queue and is the only SLA breach.

## Act 2: Drill-down on C001 (stories 7-12, 25)

1. Open C001. Check:
   - holdings, plus actual vs target allocation per asset class against the tolerance bands;
   - a single Portfolio Drift number with its definition;
   - risk profile, horizon, liquidity needs and restrictions;
   - look-through sector exposure that includes tech held via ETFs;
   - an **Approved research** panel: the approved Insights on what the Portfolio holds, with report-page citations;
   - the **proposed vs allowed Research Tilt**, bounded to +-2 pp by default.
2. Log in as `relationship_manager` and open the same client. Sensitive client fields should be masked, while the `advisor` role sees them.

## Act 3: Recommendation, grounding and the AI memo (stories 13-17, 56-60)

C001 has no Recommendation: its drift is in band, so the engine drafts none despite the concentration breach. In the recommendation panel on C002, check that:

- Trade Lines show both percentages and currency amounts;
- the rationale carries citations to report passages and engine figures;
- ungrounded claims are flagged and excluded from the memo, but still visible;
- the memo is present;
- the suitability results show pass, warning or breach, each with a rule ID and numbers;
- the wording makes clear that "Approved = cleared to act outside this system".

## Act 4: Happy path with a single approver (C017)

1. As `advisor`, open C017. Its recommendation has **no breach and is not high-impact**, so the panel shows the Advisor as the only approval step. Accept it.
2. The status should go straight to **Approved**.
3. Check that the UI does not imply any trade was placed.

## Act 5: Modify and re-check (stories 20-22)

1. On C003's recommendation, edit the Trade Lines: sell all of SGOV and buy XLK with the proceeds. That pushes a conservative Client's equity share and tech concentration over their limits.
2. Submit it. It should be saved as a **new linked version** and re-run through suitability immediately.
3. You should get a warning that a breach now needs Compliance sign-off. The previous version should show as Superseded or linked.

## Act 6: Compliance exception on C002 (stories 28-35)

1. As `advisor`, accept C002's recommendation. It should move to **Pending Compliance**, because it is still in breach of the single-position limit (SR-02) after trading. C004's XOM restriction shows on its drill-down as an SR-05 breach, but C004 has no Recommendation.
2. As `compliance_officer`, open **Approvals** and check for:
   - the breached rule ID, limit, actual value and affected Trade Line;
   - warnings, client restrictions, and the rationale with its grounding flags.
3. Try approving without a rationale. It should be refused.
4. Approve with a rationale. As a second case, have the Advisor accept C009 and block it instead. A blocked recommendation can't be approved afterwards.
5. Negative check: a recommendation the Advisor hasn't decided yet (C003's, before Act 7) should not be approvable by Compliance. Trying it should return an error.

## Act 7: Investment Committee (stories 36-38)

1. C003's recommendation is **high-impact** as drafted (turnover 25%, the SGOV sell is 25% of the Portfolio). The version modified in Act 5 is both high-impact and in breach.
2. After the Advisor (and Compliance, for the breaching version), it should appear in the `investment_committee` **Approvals** panel, with the thresholds and the reasons it reached the committee visible. The committee cannot act before Compliance.
3. Approve or reject it with a rationale.

## Act 8: RBAC and access denied (stories 43, 65)

1. As `advisor`, open `/audit` or `/governance` directly in the URL bar. You should get no view.
2. Try an API call you don't have rights for, for example `GET /api/config` as `relationship_manager`, or `POST /api/analysis/runs` as `auditor`.
3. The server should return 403, and an `access_denied` event should show up in the audit trail (checked in Act 9).

## Act 9: Auditor evidence (stories 39-46, 61)

Log in as `auditor`.

1. **Audit:** search by event type, actor, client and date range.
   - Look for `access_denied`.
   - Check that overrides (modified recommendations and exception approvals) are highlighted.
   - AI events should show model and prompt version.
   - Seed items should carry the human-verified marker.
2. Open **Lineage** for the C003 recommendation (the modified version). The chain should run report passage -> insight -> tilt (proposed and allowed) -> recommendation -> decisions.
3. Click **Verify chain**. It should report OK.
4. **Governance:** check the model card, the prompt/version log and the AI quality panel (grounding pass rate, ungrounded counts). Run the **adversarial fixtures**. A fabricated quote, a wrong number and an uncited asset call should each be flagged or blocked.

## Act 10: Supersession and the clean portfolio (stories 23, 68)

1. As `advisor`, run analysis again. Open recommendations on the same portfolio should become **Superseded**.
2. Confirm that C005 still produces no action.

## Act 11: Research Analyst reviews a house view, and the Advisor sees the result (`.scratch/research-analyst-ui/spec.md`)

The Analyst's whole job runs in the UI: land on To review, upload a house view, review its Insights, and watch the outcome reach the Advisor. The tick list, in run order, is the Research Analyst section of the checklist.

**Setup.** Start from a fresh seed (Section 0), and start the API with the committed extraction recordings, so the demo house view replays its extraction instead of calling an LLM:

```bash
APP_LLM_MODE=recorded APP_LLM_RECORDINGS_DIR=tests/fixtures/llm \
  uv run uvicorn app.main:create_app --factory --port 8000
```

`tests/fixtures/house_view_demo.txt` then always lands with 3 Insights awaiting review: Information Technology (sector, positive, page 1), Utilities (sector, negative, page 1) and equity (Asset Class, positive, page 2). Any other new text has no recording, so its extraction fails, which is how the failure path is checked. The run uploads the demo house view four times; each copy is a separate Report with its own ID.

1. **Land.** Log in as `research_analyst`. You land on **Research → To review** (`/research`). On a fresh database it shows "All caught up" with Upload Report and Browse Reports, and the badge reads 0. The **Reports** tab lists the 5 seeded Reports, each marked "Human-verified seed". Open one to see the review layout read-only: the Insight list on the left, and on the right the selected Insight with its cited page, the passage highlighted.
2. **Access.** As `advisor` or `auditor` there is no Research item in the nav, and `/research` returns them to their own first screen.
3. **Upload failures first.** In **Upload Report**, try a `.png` (refused in the dialog, nothing sent), a 21 MB file (refused, nothing sent), an empty `.txt` (the server's 422 shows inline), then any new `.txt` (it uploads, its extraction fails, and its detail offers **Upload again**).
4. **Copy 1 on Report detail.** Upload the demo house view titled "Demo house view, copy 1". The dialog shows "Extracting Insights from your Report…" and lands on the new Report with 3 Insights awaiting review. Note its ID. With the mouse:
   - **Approve** Information Technology. The selection moves to Utilities.
   - **Reject…** Utilities. The dialog will not submit without a note, so write why (e.g. "Valuation call only; not a view we act on").
   - Expand "Approval note (optional)" on equity, write a note and **Approve**. The detail says "This Report is fully reviewed", and each Insight shows its read-only record: outcome, reviewer `research_analyst`, time and note.
5. **Copies 2 and 3 on To review.** Upload two more copies. To review groups them by Report, newest first, and the badge reads 6. Review a few with the mouse, then run the 409 race: open one Insight in two sessions (normal and incognito window), approve in one, then act in the other, which shows "Already reviewed by someone else…" and moves on. Finish the rest from the keyboard: `j`/`↓` and `k`/`↑` move, `a` approves, `r` opens Reject (Escape closes it). The last review shows "All caught up".
6. **Copy 4 stays awaiting review.** Upload a fourth copy and leave it alone. Note its ID.
7. **Downstream: the Advisor's Portfolio.** Log in as `advisor` and open C001 from the Queue. The **Approved research** panel lists the approved Insights on sectors and Asset Classes that C001 holds, newest first, each with its report-page citation (click it to read the quote) and its reviewer.
   - Match rows by Report ID, not position: copies 2 and 3 are newer, so whatever was approved there sits above copy 1.
   - Copy 1's Information Technology and equity Insights are listed, cited to copy 1's ID, with reviewer `research_analyst`.
   - No row cites copy 1's ID for Utilities: the rejected Insight is absent, although C001 holds Utilities (see the look-through table).
   - Nothing from copy 4 appears, although C001 holds both sectors and equity. The panel reads from the approved-only Insight listing, so an Insight that is rejected or still awaiting review cannot reach any Advisor screen.
8. **Close the loop.** As `research_analyst`, approve copy 4's Information Technology. As `advisor`, reload C001. It now tops the panel; copy 4's other two are still absent.

In live LLM mode, rerunning analysis after step 4 also lets the Research Tilt and the rationale draw on the new approved Insights, with citations to the new Report. That depends on the model, so the deterministic check is the panel.

## Act 12: API-only roles (stories 47-55)

These have no UI, so use `curl`, or `/docs` at http://localhost:8000/docs.

- `platform_owner`: the **Config** and **Health** screens show the values in force and the component status. Change them with `PATCH /api/config`, for example by lowering the tilt bound or the high-impact threshold. Then rerun analysis and see the effect.
- `portfolio_manager`: read-only access to portfolios and config. It lands on the Config screen.

## Optional tamper test (Auditor story 42)

Stop the server and edit one row's payload in `data/app.db` (copy the DB first). On restart, **Verify chain** should name the first broken link.

## Things to note as you go

- **Cost and latency:** live mode makes an LLM call per portfolio for the narrative, so the first run is slower and costs money. Recorded mode is instant and free.
- **Provider:** live mode defaults to OpenRouter with `anthropic/claude-sonnet-5.5`. Changing `APP_LLM_MODEL` or `APP_LLM_BASE_URL` stops the committed recordings from replaying.
