# End-to-end manual check: step-by-step guide

Browser walkthrough of the main functionality against the planted synthetic scenarios. Requirements: `specs/AI_Portfolio_Rebalancing_Use_Case_Requirements_and_Scope.md` and `.scratch/ai-portfolio-rebalancing/spec.md`. A one-page tick list is in `docs/manual-e2e-checklist.md`.

Button labels below are taken from the code, not from a live run, and may differ slightly on screen.

## 0. Before you start

**LLM mode.** `.env` may be in live mode (`APP_LLM_MODE=live`, `APP_LLM_RECORD=true`). This matters for what you will see:

- The repo only ships recordings for insight extraction. In `recorded` mode, the tilt, rationale, memo and queue narrative all fail with `LlmError`. The app handles that by showing a "failed" status instead of crashing.
- For a realistic AI walkthrough, stay in live mode. Each reply is also saved as a recording, so you can switch to `recorded` for repeat runs.
- Recorded mode ships recordings only for insight extraction, so the tilt, rationale, memo and narrative steps show failed Exchanges there. In a Recommendation's AI contribution each such step shows as `recorded` and `failed` with a short reason, and latency reads "n/a (replayed)".
- A failed AI step is itself a useful check. The deterministic parts (drift, suitability, approvals) must still work.

**Reset and start** (three terminals, from the repo root):

```bash
source .venv/bin/activate
uv run python -m app.seeder            # 25 synthetic clients, deterministic
uv run python -m app.research_seed     # 5 reports + human-verified approved insights
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
| C001   | Heavy tech                     | Sector concentration through look-through       |
| C002   | Overweight energy              | Asset-class or sector drift                     |
| C003   | Cash drag                      | Minimum-cash or drift signal                    |
| C004   | Holds XOM, which is restricted | Restriction breach, so Compliance is required   |
| C005   | Clean portfolio                | No action, so the system doesn't over-recommend |

## Act 1: Advisor builds the queue (stories 1-6, 66-68)

1. Log in as `advisor`. The nav should show Queue, and no Audit, Governance or Config items.
2. On **Queue**, start an analysis run (the on-demand button). It scores all 25 portfolios.
3. Check each row for:
   - a score from 0 to 100 and a High/Medium/Low label (High >= 70, Medium >= 40);
   - a four-part breakdown of drift, risk, opportunity and urgency;
   - a cited "why now" narrative (or a "failed" status if the LLM is unavailable);
   - an SLA-breached flag.
4. Filter by label and by risk profile, and sort by review-due date.
5. Confirm C001-C004 rank above C005, and that C005 sits at Low.

## Act 2: Drill-down on C001 (stories 7-12, 25)

1. Open C001. Check:
   - holdings, plus actual vs target allocation per asset class against the tolerance bands;
   - a single Portfolio Drift number with its definition;
   - risk profile, horizon, liquidity needs and restrictions;
   - look-through sector exposure that includes tech held via ETFs;
   - relevant approved insights with report-page citations;
   - the **proposed vs allowed Research Tilt**, bounded to +-2 pp by default.
2. Log in as `relationship_manager` and open the same client. Sensitive client fields should be masked, while the `advisor` role sees them.

## Act 3: Recommendation, grounding and the AI memo (stories 13-17, 56-60)

In the recommendation panel on C001, check that:

- Trade Lines show both percentages and currency amounts;
- the rationale carries citations to report passages and engine figures;
- ungrounded claims are flagged and excluded from the memo, but still visible;
- the memo is present;
- the suitability results show pass, warning or breach, each with a rule ID and numbers;
- the wording makes clear that "Approved = cleared to act outside this system".

## Act 4: Happy path with a single approver (C002 or C003)

1. As `advisor`, on a recommendation with **no breach and not high-impact**, accept it.
2. The status should go straight to **Approved**.
3. Check that the UI does not imply any trade was placed.

## Act 5: Modify and re-check (stories 20-22)

1. On a recommendation, edit the Trade Lines. For example, add a buy of an overweight sector, or increase a single position above the limit.
2. Submit it. It should be saved as a **new linked version** and re-run through suitability immediately.
3. You should get a warning that a breach now needs Compliance sign-off. The previous version should show as Superseded or linked.

## Act 6: Compliance exception on C004 (stories 28-35)

1. As `advisor`, accept C004's recommendation. It should move to **Pending Compliance**, because of the XOM restriction.
2. As `compliance_officer`, open **Approvals** and check for:
   - the breached rule ID, limit, actual value and affected Trade Line;
   - warnings, client restrictions, and the rationale with its grounding flags.
3. Try approving without a rationale. It should be refused.
4. Approve with a rationale. As a second case, use a breaching recommendation and block it instead.
5. Negative check: a recommendation the Advisor hasn't decided yet should not be approvable by Compliance. Trying it should return an error.

## Act 7: Investment Committee (stories 36-38)

1. Make a **high-impact** recommendation, with turnover >= 15% or a single line >= 10%. The easiest way is to modify the lines to be large.
2. After the Advisor (and Compliance, if breached), it should appear in the `investment_committee` **Approvals** panel, with the thresholds visible.
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
2. Open **Lineage** for the C004 recommendation. The chain should run report passage -> insight -> tilt (proposed and allowed) -> recommendation -> decisions.
3. Click **Verify chain**. It should report OK.
4. **Governance:** check the model card, the prompt/version log and the AI quality panel (grounding pass rate, ungrounded counts). Run the **adversarial fixtures**. A fabricated quote, a wrong number and an uncited asset call should each be flagged or blocked.

## Act 10: Supersession and the clean portfolio (stories 23, 68)

1. As `advisor`, run analysis again. Open recommendations on the same portfolio should become **Superseded**.
2. Confirm that C005 still produces no action.

## Act 11: API-only roles (stories 47-55)

These have no UI, so use `curl`, or `/docs` at http://localhost:8000/docs.

- `research_analyst`: uploading and Insight Reviews now have a UI: Research opens on **To review**, every Insight awaiting review across Reports, grouped by Report ("All caught up" on a fresh database); **Upload Report** is in the header; **Approve** (optional note) or **Reject…** (required note) sit at the top of each Insight awaiting review, on To review and on a Report's detail alike (see the Research Analyst section of the checklist). The 409 race needs two browser sessions on the same Insight. Start the API with `APP_LLM_RECORDINGS_DIR=tests/fixtures/llm` so the demo house view (`tests/fixtures/house_view_demo.txt`) replays its committed extraction and lands with 3 Insights **pending**; any other new text has no recording and shows the failed extraction with **Upload again**. Pending Insights do not affect any tilt until approved.
- `platform_owner`: `GET /api/health` and `PATCH /api/config`. Lower the tilt bound or the high-impact threshold, rerun analysis, and see the effect.
- `portfolio_manager`: read-only access to portfolios and config.

## Optional tamper test (Auditor story 42)

Stop the server and edit one row's payload in `data/app.db` (copy the DB first). On restart, **Verify chain** should name the first broken link.

## Things to note as you go

- **Cost and latency:** live mode makes an LLM call per portfolio for the narrative, so the first run is slower and costs money.
- **Provider mismatch to check:** the README says the default provider is Anthropic, but `.env` may point at OpenAI. Check that this is intentional.
- **Spec gap:** the spec lists "Config" and "Health" in the nav, but `main.tsx` has no routes for them, so they hit the placeholder page. That is probably expected, since those roles are API-only.
