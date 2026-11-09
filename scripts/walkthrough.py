"""The scripted demo walkthrough: the planted scenarios from the Queue to the Auditor's evidence, through the HTTP API.

Run it with `uv run python -m scripts.walkthrough`. It builds a throwaway app on a fresh database in recorded mode,
seeds it exactly as the replay tests do (synthetic Clients, research seeds, one Analysis Run by the advisor) and then
plays each act as the role that owns it, printing every claim it checks with the evidence. It exits non-zero if any
claim fails. Nothing touches the network or `data/app.db`: AI steps replay the committed recordings in
`tests/fixtures/llm` (recorded with `uv run python -m tests.fixtures.regenerate`).

The browser walkthrough of the same story is `docs/manual-e2e-guide.md`. The claims follow ADR-0001 (the engine owns
every number), ADR-0002 (the hash-chained audit trail and its verification), ADR-0003 (real market data, synthetic
Clients) and ADR-0004 (every LLM call an Exchange anchored in the chain).

Planted scenarios after the first Analysis Run (fixed by the seed and the committed market snapshot):
- C001 heavy tech and C004 restricted XOM: Suitability breaches on what is held, drift in band, so no Recommendation.
- C002 overweight energy: a Recommendation that stays in breach, so the Advisor's accept needs Compliance (and the
  Investment Committee when its Research Tilt makes it high-impact, as the committed recordings do).
- C003 cash drag: a clean but high-impact Recommendation, so the Advisor's accept needs the Investment Committee.
- C005 clean: no breach, no drift, no Recommendation.
The single-approver and Compliance-block cases are picked from the Queue by their approval route, since the recorded
Research Tilts shape the Trade Lines of every other Portfolio.
"""

import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic_ai.models import Model

from app.main import create_app
from app.seeder import PLANTED as PLANTED_IDS
from tests.fixtures.suggested_questions import login, replay_settings, seed_demo
from tests.runs import run_and_wait

PLANTED = tuple(PLANTED_IDS.values())


@dataclass(frozen=True)
class Check:
    act: str
    claim: str
    ok: bool
    evidence: str


class Walkthrough:
    """Plays the acts in order against a seeded app. `checks` holds every claim checked, passed or not."""

    def __init__(self, app: FastAPI, run_timeout: float = 60):
        self.app = app
        self.run_timeout = run_timeout
        self.checks: list[Check] = []
        self._act = ""
        self._clients: dict[str, TestClient] = {}
        self._approved: list[int] = []  # Recommendations the walkthrough took to Approved

    # -- plumbing -------------------------------------------------------------------------------------------------

    def as_(self, role: str) -> TestClient:
        if role not in self._clients:
            self._clients[role] = login(self.app, role)
        return self._clients[role]

    def check(self, claim: str, ok: bool, evidence: object = "") -> bool:
        self.checks.append(Check(self._act, claim, bool(ok), str(evidence)))
        return bool(ok)

    def get(self, role: str, path: str, **params: Any) -> Any:
        r = self.as_(role).get(path, params=params)
        assert r.status_code == 200, f"{role} GET {path}: {r.status_code} {r.text}"
        return r.json()

    def portfolio(self, cid: str, role: str = "advisor") -> dict:
        return self.get(role, f"/api/portfolios/{cid}")

    def rec(self, cid: str) -> dict:
        rec = self.portfolio(cid)["recommendation"]
        assert rec is not None, f"{cid} has no Recommendation"
        return rec

    def decide(self, rec_id: int, body: dict) -> Any:
        return self.as_("advisor").post(f"/api/recommendations/{rec_id}/decision", json=body)

    def step(self, role: str, step: str, rec_id: int, action: str, rationale: str | None) -> Any:
        return self.as_(role).post(
            f"/api/recommendations/{rec_id}/{step}", json={"action": action, "rationale": rationale}
        )

    def events(self, **params: Any) -> list[dict]:
        return self.get("auditor", "/api/audit/events", limit=200, **params)["items"]

    # -- the acts -------------------------------------------------------------------------------------------------

    def run(self) -> list[Check]:
        acts: list[tuple[str, Callable[[], None]]] = [
            ("1 Queue", self.queue),
            ("2 Drill-down", self.drill_down),
            ("3 Recommendation", self.recommendation),
            ("4 Single approver, Compliance exception and block", self.compliance),
            ("5 Modify and the Investment Committee", self.modify_and_committee),
            ("6 Access denied", self.access_denied),
            ("7 Auditor evidence", self.auditor),
            ("8 Supersession and the clean Portfolio", self.supersession),
        ]
        for name, act in acts:
            self._act = name
            act()
        return self.checks

    def queue(self) -> None:
        q = self.get("advisor", "/api/queue")
        items = q["items"]
        by_id = {i["portfolio_id"]: i for i in items}
        scores = [i["score"] for i in items]
        self.check(
            "all 25 Portfolios are scored and ranked by score",
            len(items) == 25 and scores == sorted(scores, reverse=True),
            f"{len(items)} rows, top {items[0]['portfolio_id']} {scores[0]}",
        )
        self.check(
            "every row breaks its score into drift, risk, opportunity and urgency",
            all({c["name"] for c in i["components"]} == {"drift", "risk", "opportunity", "urgency"} for i in items),
        )
        self.check(
            "labels follow the thresholds (High >= 70, Medium >= 40, else Low)",
            all(i["label"] == ("High" if i["score"] >= 70 else "Medium" if i["score"] >= 40 else "Low") for i in items),
        )
        c5 = by_id["C005"]
        self.check(
            "the clean Portfolio C005 ranks below every other planted scenario",
            all(by_id[c]["score"] > c5["score"] for c in ("C001", "C002", "C003", "C004")),
            f"C005 {c5['score']} {c5['label']}",
        )
        breached = [i["portfolio_id"] for i in items if i["sla_breached"]]
        self.check(
            "SLA breaches are flagged (C003 is 30 days past review-due)",
            "C003" in breached,
            f"{len(breached)} breached",
        )
        narrated = [i for i in items if i["narrative"]["status"] == "complete"]
        self.check(
            "every row carries an AI 'why this client, why now' narrative",
            len(narrated) == len(items),
            f"{len(narrated)}/{len(items)} complete",
        )
        cited = [i for i in narrated if i["narrative"]["claims"]]
        self.check(
            "narratives cite their claims", bool(cited), f"{sum(len(i['narrative']['claims']) for i in cited)} claims"
        )
        high = self.get("advisor", "/api/queue", label="High")["items"]
        self.check(
            "the Queue filters by label", bool(high) and all(i["label"] == "High" for i in high), f"{len(high)} High"
        )
        by_due = self.get("advisor", "/api/queue", sort="review_due", order="asc")["items"]
        dues = [i["review_due"] for i in by_due]
        self.check("the Queue sorts by review-due date", dues == sorted(dues), f"first due {dues[0]}")

    def drill_down(self) -> None:
        p = self.portfolio("C001")
        it = next(s for s in p["sector_exposure"] if s["sector"] == "Information Technology")
        self.check(
            "C001 shows Holdings, Portfolio Drift and the Tolerance Band",
            bool(p["holdings"]) and p["drift"]["portfolio_drift_pp"] is not None and p["drift"]["tolerance_band"],
            f"drift {p['drift']['portfolio_drift_pp']} pp, band {p['drift']['tolerance_band']}",
        )
        self.check(
            "look-through exposes tech held through funds",
            it["via_funds_pct"] > 0,
            f"IT {it['weight_pct']:.1f}% ({it['via_funds_pct']:.1f}% via funds)",
        )
        rules = {r["rule_id"]: r for r in p["suitability"]["rules"]}
        self.check(
            "heavy tech breaches sector concentration (SR-03) with the numbers",
            rules["SR-03"]["status"] == "breach",
            rules["SR-03"]["message"],
        )
        self.check("drift is in band, so the engine drafts no Recommendation for C001", p["recommendation"] is None)
        insights = self.get("advisor", "/api/insights")["items"]  # approved only, by contract
        self.check(
            "approved, cited research is available to the Advisor", bool(insights), f"{len(insights)} approved Insights"
        )
        c4 = {r["rule_id"]: r for r in self.portfolio("C004")["suitability"]["rules"]}
        self.check(
            "C004 holds restricted XOM: Client Restrictions (SR-05) breach",
            c4["SR-05"]["status"] == "breach",
            c4["SR-05"]["message"],
        )
        masked = self.portfolio("C001", role="relationship_manager")["client"]
        self.check(
            "the Relationship Manager sees the Client's name and email masked",
            masked["name"] is None and masked["email"] is None and p["client"]["email"],
            "advisor sees them; RM gets null",
        )

    def recommendation(self) -> None:
        r = self.rec("C002")
        lines = r["trade_lines"]
        self.check(
            "C002's Recommendation is concrete: Trade Lines in % and currency",
            bool(lines) and all(line["pct_of_portfolio"] and line["amount"] for line in lines),
            f"{len(lines)} lines, turnover {r['turnover_pct']}%",
        )
        self.check(
            "post-trade Suitability is evaluated beside it",
            r["suitability"]["status"] == "breach",
            [x["rule_id"] for x in r["suitability"]["rules"] if x["status"] == "breach"],
        )
        route = r["approval"]["required_steps"]
        self.check(
            "the approval route is known before deciding: the breach adds Compliance",
            route[:2] == ["advisor", "compliance"] and r["approval"]["needs_compliance"],
            " -> ".join(route) + (f" ({r['approval']['reasons'][0]})" if r["approval"]["reasons"] else ""),
        )
        tilt, narrative = r["research"]["tilt"], r["research"]["narrative"]
        self.check(
            "the AI Research Tilt was proposed and bounded by the engine",
            tilt["status"] == "ok" and tilt["bound_pp"] == 2.0,
            f"{tilt['status']}, {len(tilt['entries'])} entries, bound ±{tilt['bound_pp']} pp",
        )
        self.check(
            "every allowed tilt is within the bound",
            all(abs(e["allowed_pp"]) <= tilt["bound_pp"] for e in tilt["entries"]),
        )
        self.check(
            "an AI rationale and advisor memo are attached",
            narrative["status"] == "complete" and bool(narrative["memo"]),
            (narrative["memo"] or "")[:80],
        )
        claims = narrative["claims"]
        ungrounded = [c for c in claims if not c["grounded"]]
        self.check(
            "its claims went through the grounding validator",
            bool(claims),
            f"{len(claims) - len(ungrounded)} grounded, {len(ungrounded)} ungrounded (kept visible, excluded from the memo)",
        )

    def first_with_route(self, route: list[str], exclude: tuple[str, ...]) -> tuple[str, dict]:
        """The highest-ranked Portfolio, outside `exclude`, whose open Recommendation needs exactly `route`. Chosen by
        route, not by Client, because the recorded Research Tilts shape the Trade Lines and so the route."""
        for item in self.get("advisor", "/api/queue")["items"]:
            cid = item["portfolio_id"]
            rec = None if cid in exclude else self.portfolio(cid)["recommendation"]
            if rec and rec["status"] == "pending_advisor" and rec["approval"]["required_steps"] == route:
                return cid, rec
        raise AssertionError(f"no Recommendation needs exactly {route}")

    def compliance(self) -> None:
        cid, simple = self.first_with_route(["advisor"], exclude=PLANTED)  # neither in breach nor high-impact
        self.check(f"{cid}'s Recommendation needs the Advisor only", True, simple["approval"]["required_steps"])
        out = self.decide(simple["id"], {"action": "accept"}).json()["recommendation"]
        self.check(
            "the Advisor's accept clears it to Approved at once",
            out["status"] == "approved",
            out["status"],
        )
        self._approved.append(simple["id"])
        c3 = self.rec("C003")
        early = self.step("compliance_officer", "compliance", c3["id"], "approve", "too early")
        self.check("Compliance cannot act before the Advisor has decided", early.status_code == 409, early.status_code)
        r = self.rec("C002")
        out = self.decide(r["id"], {"action": "accept"}).json()
        self.check(
            "the Advisor's accept on a breach goes to Compliance, not Approved",
            out["recommendation"]["status"] == "pending_compliance",
            out["recommendation"]["status"],
        )
        pending = self.get("compliance_officer", "/api/approvals")["items"]
        row = next((i for i in pending if i["portfolio_id"] == "C002"), None)
        self.check(
            "it is on the Compliance Officer's approvals list with the breached rules",
            row is not None and bool(row["rules"]),
            row and [x["rule_id"] for x in row["rules"]],
        )
        blank = self.step("compliance_officer", "compliance", r["id"], "approve", "  ")
        self.check("an exception approval without a rationale is refused", blank.status_code == 422, blank.status_code)
        ok = self.step(
            "compliance_officer", "compliance", r["id"], "approve", "Client signed a concentration waiver"
        ).json()
        high_impact = "committee" in r["approval"]["required_steps"]
        self.check(
            "approving the exception with a rationale moves it on its route",
            ok["recommendation"]["status"] == ("pending_committee" if high_impact else "approved")
            and ok["decision"]["action"] == "approve_exception",
            ok["recommendation"]["status"],
        )
        if high_impact:
            done = self.step("investment_committee", "committee", r["id"], "approve", "Within the house view").json()
            self.check(
                "as it is also high-impact, the Investment Committee's approval clears it",
                done["recommendation"]["status"] == "approved",
                done["recommendation"]["status"],
            )
        self._approved.append(r["id"])
        block_id, c9 = self.first_with_route(["advisor", "compliance"], exclude=PLANTED)
        self.decide(c9["id"], {"action": "accept"})
        blocked = self.step(
            "compliance_officer", "compliance", c9["id"], "block", "Breach is not acceptable for this Client"
        ).json()
        self.check(
            "Compliance can block a breaching Recommendation instead",
            blocked["recommendation"]["status"] == "rejected" and blocked["decision"]["action"] == "block",
            f"{block_id} {blocked['recommendation']['status']}",
        )
        again = self.step("compliance_officer", "compliance", c9["id"], "approve", "changed my mind")
        self.check(
            "a blocked Recommendation cannot be approved afterwards", again.status_code == 409, again.status_code
        )

    def modify_and_committee(self) -> None:
        v1 = self.rec("C003")
        self.check(
            "C003 as drafted is clean but high-impact: Advisor, then the Investment Committee",
            v1["approval"]["required_steps"] == ["advisor", "committee"] and not v1["approval"]["needs_compliance"],
            v1["approval"]["reasons"][:1],
        )
        sgov = next(h for h in self.portfolio("C003")["holdings"] if h["symbol"] == "SGOV")
        lines = [
            {"account_id": sgov["account_id"], "symbol": "SGOV", "side": "sell", "quantity": sgov["quantity"]},
            {
                "account_id": sgov["account_id"],
                "symbol": "XLK",
                "side": "buy",
                "quantity": int(sgov["market_value"] // 100),
            },
        ]
        out = self.decide(
            v1["id"], {"action": "modify", "rationale": "Client wants more growth", "trade_lines": lines}
        ).json()
        v2 = out["recommendation"]
        self.check(
            "a modification is saved as a new linked version",
            v2["version"] == 2 and v2["parent_id"] == v1["id"],
            f"v{v2['version']} parent {v2['parent_id']}",
        )
        self.check(
            "it is re-checked at once and the new breach is reported",
            bool(out["new_breaches"]),
            [b["rule_id"] for b in out["new_breaches"]],
        )
        self.check(
            "it now needs Advisor, Compliance and the Investment Committee",
            v2["approval"]["required_steps"] == ["advisor", "compliance", "committee"],
            v2["approval"]["reasons"][:1],
        )
        self.decide(v2["id"], {"action": "accept"})
        early = self.step("investment_committee", "committee", v2["id"], "approve", "early")
        self.check("the Investment Committee cannot act before Compliance", early.status_code == 409, early.status_code)
        mid = self.step("compliance_officer", "compliance", v2["id"], "approve", "Waiver on file").json()
        self.check(
            "after the exception it waits for the Investment Committee",
            mid["recommendation"]["status"] == "pending_committee",
        )
        done = self.step("investment_committee", "committee", v2["id"], "approve", "Large but within mandate").json()
        self.check(
            "the Investment Committee's approval completes it",
            done["recommendation"]["status"] == "approved",
            done["recommendation"]["status"],
        )
        self._approved.append(v2["id"])

    def access_denied(self) -> None:
        attempts = [
            ("auditor", "POST", "/api/analysis/runs"),
            ("advisor", "GET", "/api/audit/events"),
            ("relationship_manager", "PATCH", "/api/config"),
        ]
        for role, method, path in attempts:
            r = self.as_(role).request(method, path, json={} if method != "GET" else None)
            self.check(f"{role} is refused {method} {path}", r.status_code == 403, r.status_code)

    def auditor(self) -> None:
        denied = self.events(type="access_denied")
        self.check("each refusal is an access_denied Audit Event", len(denied) >= 3, f"{len(denied)} events")
        # C002: its Research Tilt drew on approved Insights, so its lineage reaches back to the Report passages.
        c2 = self.rec("C002")
        lineage = self.get("auditor", f"/api/recommendations/{c2['id']}/lineage")["nodes"]
        stages = {n["stage"] for n in lineage}
        self.check(
            "C002's lineage runs Report -> Insight -> Research Tilt -> Recommendation -> Decision",
            {"report", "insight", "research_tilt", "recommendation", "decision"} <= stages,
            f"{len(lineage)} events: " + ", ".join(sorted(stages)),
        )
        c3 = self.rec("C003")
        c3_lineage = self.get("auditor", f"/api/recommendations/{c3['id']}/lineage")["nodes"]
        overrides = {n["type"] for n in c3_lineage if n["override"]}
        self.check(
            "on C003, the overrides (the modification and the exception) are highlighted",
            overrides >= {"recommendation_modified", "exception_approved"},
            sorted(overrides),
        )
        self.check(
            "C002's seed-approved research carries the human-verified marker",
            any(n["human_verified"] for n in lineage),
        )
        ai = [n for n in lineage if n["actor"].get("model")]
        self.check(
            "AI events name their model and prompt version",
            bool(ai) and all(n["actor"].get("prompt_version") for n in ai),
            ai and f"{ai[0]['actor']['model']} {ai[0]['actor']['prompt_version']}",
        )
        v = self.get("auditor", "/api/audit/verify")
        self.check(
            "the audit chain and the LLM Exchanges verify",
            v["valid"] and v["first_broken_id"] is None,
            f"{v['checked']} events, {v['exchanges_checked']} Exchanges",
        )
        g = self.get("auditor", "/api/governance")
        self.check(
            "the model card names the model behind the recordings",
            bool(g["model_card"]["model"]),
            f"{g['model_card']['model']} via {g['model_card']['llm_endpoint']}",
        )
        q = g["quality"]
        self.check(
            "the AI quality panel reports a grounding pass rate",
            q["checks"] > 0 and q["pass_rate"] is not None,
            f"{q['claims_grounded']}/{q['claims_total']} grounded",
        )
        fx = self.as_("auditor").post("/api/governance/fixtures/run").json()
        self.check(
            "adversarial fixtures (fabricated quote, wrong number, uncited call) are all caught",
            fx["passed"] == fx["total"],
            f"{fx['passed']}/{fx['total']}",
        )

    def supersession(self) -> None:
        open_before = [
            i["portfolio_id"]
            for i in self.get("advisor", "/api/queue")["items"]
            if (p := self.portfolio(i["portfolio_id"]))["recommendation"]
            and p["recommendation"]["status"] == "pending_advisor"
        ]
        old = {cid: self.rec(cid)["id"] for cid in open_before}
        run_and_wait(self.as_("advisor"), self.run_timeout)
        superseded = [
            cid
            for cid, rid in old.items()
            if self.get("advisor", f"/api/recommendations/{rid}")["status"] == "superseded"
        ]
        self.check(
            "a new Analysis Run supersedes every open Recommendation",
            bool(old) and superseded == list(old),
            f"{len(superseded)}/{len(old)} superseded",
        )
        self.check(
            "Approved Recommendations keep their outcome",
            [self.get("advisor", f"/api/recommendations/{rid}")["status"] for rid in self._approved]
            == ["approved"] * len(self._approved),
            f"{len(self._approved)} still approved",
        )
        self.check(
            "the clean Portfolio C005 still produces no action", self.portfolio("C005")["recommendation"] is None
        )


def walk(model: Model | None = None, run_timeout: float = 60) -> list[Check]:
    """Plays the walkthrough on a fresh, seeded throwaway app. `model` replaces the replay Model behind capture (for
    recording), which also needs a longer `run_timeout` for its live Analysis Runs."""
    with tempfile.TemporaryDirectory() as tmp:
        app = create_app(replay_settings(Path(tmp)))
        if model is not None:
            app.state.llm.model = model
        seed_demo(app, run_timeout)
        return Walkthrough(app, run_timeout).run()


def main() -> int:
    checks = walk()
    act = None
    for c in checks:
        if c.act != act:
            act = c.act
            print(f"\nAct {act}")
        print(f"  {'PASS' if c.ok else 'FAIL'}  {c.claim}" + (f"  [{c.evidence}]" if c.evidence else ""))
    failed = [c for c in checks if not c.ok]
    print(f"\n{len(checks) - len(failed)}/{len(checks)} claims hold")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
