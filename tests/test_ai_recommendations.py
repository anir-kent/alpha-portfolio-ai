"""Seam: AI-assisted Recommendations through the HTTP API (ADR-0001). The LLM proposes a Research Tilt from approved
Insights and look-through exposure; the engine clips it to the configured bound before it moves any Trade Line, and
writes rationale + memo that the grounding validator holds to citations. The LLM is a stub; the engine is real.

Planted C003 (conservative, ~$ millions): equity 20% (SPY 10, XLV 5, XLP 5) vs 20% target; cash 40% vs 15%; bonds 40% vs 65%.
Without a tilt there are no equity Trade Lines. Bound defaults to 2.0 pp (spec), so an equity tilt of +5 must trade ~2%.
"""
import json

import pytest
from sqlalchemy import select

from app import research_tilt
from app.db import AuditEventRow
from app.llm import LlmError, LlmResponse, RecordedLlm
from tests.runs import run_and_wait
from tests.test_portfolio import url
from tests.test_queue import seeded  # noqa: F401  (fixture)
from tests.test_research import upload

EQUITY_FUNDS = {"SPY", "XLV", "XLP", "XLK", "XLI"}


class StubLlm:
    """Replays Insight extraction from the committed recordings; tilt and narrative come from the test."""

    def __init__(self, delegate, tilt=None, narrative=None, priority_narrative=None):
        self.delegate, self.tilt, self.narrative, self.calls = delegate, tilt, narrative, []
        self.priority_narrative = priority_narrative

    def complete(self, request):
        self.calls.append(request)
        handler = {
            "research_tilt": self.tilt, "recommendation_narrative": self.narrative, "priority_narrative": self.priority_narrative,
        }.get(request.task, "delegate")
        if handler == "delegate":
            return self.delegate.complete(request)
        if handler is None:
            raise LlmError(f"no stub for {request.task}")
        return LlmResponse(handler(json.loads(request.user)), "stub-model-1", request.prompt_version)


@pytest.fixture
def ai(app, login, seeded):  # noqa: F811
    """Approved Insights from the demo house view (Information Technology +, Utilities -, equity +) and a stub LLM."""
    analyst = login("research_analyst")
    report = upload(analyst).json()
    ids = {i["subject"]: i["id"] for i in report["insights"]}
    state = type("State", (), {})()
    state.ids, state.report_id, state.analyst, state.advisor = ids, report["id"], analyst, login("advisor")
    state.stub = StubLlm(app.state.llm)
    app.state.llm = state.stub

    def approve(*subjects):
        for s in subjects:
            assert analyst.post(f"/api/insights/{ids[s]}/decision", json={"action": "approve", "note": "ok"}).status_code == 200

    def run():
        run_and_wait(state.advisor)
        return state.advisor.get(url("C003")).json()["recommendation"]

    state.approve, state.run = approve, run
    return state


def tilt_for(ai, **by_subject):
    """A stub tilt reply proposing the given pp per subject name (equity=5.0, Information_Technology=...)."""

    def reply(payload):
        out = []
        for ins in payload["insights"]:
            key = ins["subject"].replace(" ", "_")
            if key in by_subject:
                out.append({"insight_id": ins["id"], "impact": "tailwind", "tilt_pp": by_subject[key]})
        return {"tilts": out}

    ai.stub.tilt = reply


def equity_buy_pct(rec):
    return sum(l["pct_of_portfolio"] for l in rec["trade_lines"] if l["side"] == "buy" and l["symbol"] in EQUITY_FUNDS)


def entry(rec, subject):
    return next(e for e in rec["research"]["tilt"]["entries"] if e["subject"] == subject)


def audit_events(app, rec_id, *types):
    with app.state.session_factory() as db:
        return list(db.scalars(
            select(AuditEventRow).where(AuditEventRow.recommendation_id == str(rec_id), AuditEventRow.type.in_(types))
            .order_by(AuditEventRow.id)
        ))


# --- the clip: the safety-critical invariant ---------------------------------------------------------------------

@pytest.mark.parametrize("proposed,bound,allowed", [(5.0, 2.0, 2.0), (-5.0, 2.0, -2.0), (1.5, 2.0, 1.5), (-0.5, 2.0, -0.5), (3.0, 0.0, 0.0)])
def test_clip_never_exceeds_the_bound(proposed, bound, allowed):
    assert research_tilt.clip_tilt(proposed, bound) == allowed


# --- tilt clipping and its record ---------------------------------------------------------------------------------

def test_over_bound_tilt_is_clipped_before_it_moves_trade_lines(ai):
    ai.approve("equity")
    tilt_for(ai, equity=5.0)
    rec = ai.run()
    e = entry(rec, "equity")
    assert (e["proposed_pp"], e["allowed_pp"], e["clipped"]) == (5.0, 2.0, True)
    assert rec["research"]["tilt"]["bound_pp"] == 2.0
    assert 1.5 <= equity_buy_pct(rec) <= 2.0  # the engine traded the allowed 2 pp, not the proposed 5


def test_without_a_tilt_the_rule_based_recommendation_has_no_equity_trades(ai):
    ai.approve("equity")
    ai.stub.tilt = lambda payload: {"tilts": []}
    rec = ai.run()
    assert equity_buy_pct(rec) == 0 and rec["research"]["tilt"]["entries"] == []


def test_proposed_and_allowed_tilt_are_in_the_audit_chain(app, ai):
    ai.approve("equity")
    tilt_for(ai, equity=5.0)
    rec = ai.run()
    proposed, applied = audit_events(app, rec["id"], "research_tilt_proposed", "research_tilt_applied")
    assert (proposed.actor_kind, proposed.model, proposed.prompt_version) == ("system", "stub-model-1", "research_tilt@v1")
    assert json.loads(proposed.payload_json)["tilts"] == [
        {"insight_id": ai.ids["equity"], "subject": "equity", "proposed_pp": 5.0}]
    payload = json.loads(applied.payload_json)
    assert payload["bound_pp"] == 2.0 and payload["tilts"][0]["proposed_pp"] == 5.0 and payload["tilts"][0]["allowed_pp"] == 2.0
    assert json.loads(applied.parent_ids_json) == [proposed.id]
    drafted = audit_events(app, rec["id"], "recommendation_drafted")[0]
    assert applied.id in json.loads(drafted.parent_ids_json)


def test_the_bound_is_configurable(login, ai):
    assert login("platform_owner").patch("/api/config", json={"tilt_bound_pp": 1.0}).status_code == 200
    ai.approve("equity")
    tilt_for(ai, equity=5.0)
    e = entry(ai.run(), "equity")
    assert (e["proposed_pp"], e["allowed_pp"]) == (5.0, 1.0)


def test_a_proposal_against_the_insight_direction_is_not_allowed(ai):
    ai.approve("equity")  # the Report is positive on equity
    tilt_for(ai, equity=-1.0)
    e = entry(ai.run(), "equity")
    assert (e["proposed_pp"], e["allowed_pp"]) == (-1.0, 0.0) and "direction" in e["reason"]


# --- sector tilt: look-through exposure and the sector sleeve --------------------------------------------------------

def test_sector_tilt_within_bound_switches_spy_into_the_sector_etf(ai):
    ai.approve("Information Technology")
    tilt_for(ai, Information_Technology=1.5)
    rec = ai.run()
    e = entry(rec, "Information Technology")
    assert (e["proposed_pp"], e["allowed_pp"], e["clipped"], e["subject_kind"]) == (1.5, 1.5, False, "sector")
    assert e["exposure_pct"] == pytest.approx(0.10 * 0.31 * 100, abs=0.5)  # C003 holds 10% SPY; SPY is ~31% technology
    buys = {l["symbol"]: l for l in rec["trade_lines"] if l["side"] == "buy"}
    sells = {l["symbol"]: l for l in rec["trade_lines"] if l["side"] == "sell"}
    assert buys["XLK"]["pct_of_portfolio"] == pytest.approx(1.5, abs=0.2)
    assert sells["SPY"]["pct_of_portfolio"] == pytest.approx(1.5, abs=0.2)
    assert not ({l["symbol"] for l in rec["trade_lines"] if l["side"] == "buy"} & {"SPY"})


def test_pending_and_rejected_insights_cannot_influence_a_tilt(app, ai):
    ai.approve("Information Technology")  # Utilities (pending) and equity (pending) are not approved
    tilt_for(ai, Information_Technology=1.0)
    sent = []

    def reply(p):
        sent.append(p)
        return {"tilts": [
            {"insight_id": ai.ids["Utilities"], "impact": "headwind", "tilt_pp": -2.0},
            {"insight_id": ai.ids["equity"], "impact": "tailwind", "tilt_pp": 2.0},
            {"insight_id": ai.ids["Information Technology"], "impact": "tailwind", "tilt_pp": 1.0}]}

    ai.stub.tilt = reply
    rec = ai.run()
    assert {i["id"] for i in sent[0]["insights"]} == {ai.ids["Information Technology"]}  # the LLM is only shown approved
    assert [e["subject"] for e in rec["research"]["tilt"]["entries"]] == ["Information Technology"]
    assert equity_buy_pct(rec) < 1.2  # the equity proposal was dropped, only the 1 pp technology switch remains
    dropped = json.loads(audit_events(app, rec["id"], "research_tilt_applied")[0].payload_json)["dropped"]
    assert {d["insight_id"] for d in dropped} == {ai.ids["Utilities"], ai.ids["equity"]}


def test_no_llm_call_without_approved_insights(ai):
    rec = ai.run()
    assert ai.stub.calls == [] or all(c.task == "insight_extraction" for c in ai.stub.calls)
    assert rec["research"] is None


# --- LLM failure falls back to the plain rule-based Recommendation ---------------------------------------------------

def test_tilt_failure_falls_back_to_the_rule_based_recommendation_and_is_audited(app, ai):
    ai.approve("equity")
    ai.stub.tilt = None  # raises LlmError
    rec = ai.run()
    assert equity_buy_pct(rec) == 0 and rec["research"]["tilt"]["status"] == "failed"
    assert rec["trade_lines"], "the Recommendation still exists"
    (failed,) = audit_events(app, rec["id"], "research_tilt_proposed")
    assert json.loads(failed.payload_json)["status"] == "failed"
    assert not audit_events(app, rec["id"], "research_tilt_applied")


# --- rationale and memo: engine numbers, grounded claims only --------------------------------------------------------

def narrative_reply(payload):
    """A model that writes one faithful claim and three the validator must catch."""
    f = payload["figures"]
    equity = next(i for i in payload["insights"] if i["subject"] == "equity")
    report = {"kind": "report", "report_id": equity["report_id"], "page": equity["page"], "quote": equity["passage"]}
    return {"claims": [
        {"text": f"Research favours equity, so the engine allowed a {f['tilt.equity.allowed_pp']:.1f} pp tilt.",
         "asset": "equity", "citations": [report, {"kind": "engine", "figure": "tilt.equity.allowed_pp"}]},
        {"text": "Equities will return 40% next year.", "asset": "equity",
         "citations": [{**report, "quote": "Equities will return 40% next year."}]},
        {"text": "Turnover is 99.9% of the Portfolio.", "citations": [{"kind": "engine", "figure": "turnover_pct"}]},
        {"text": "Bonds look unattractive.", "asset": "bond", "citations": []},
    ]}


@pytest.fixture
def written(ai):
    ai.approve("equity")
    tilt_for(ai, equity=5.0)
    ai.stub.narrative = narrative_reply
    return ai.run()


def test_rationale_shows_every_claim_with_flags_and_the_memo_keeps_only_grounded_ones(written):
    n = written["research"]["narrative"]
    assert [c["grounded"] for c in n["claims"]] == [True, False, False, False]
    assert [c["memo_eligible"] for c in n["claims"]] == [True, False, False, False]
    assert {"quote_not_found", "number_mismatch"} <= {i["code"] for i in n["claims"][1]["issues"]}
    assert "number_mismatch" in {i["code"] for i in n["claims"][2]["issues"]}
    assert "uncited" in {i["code"] for i in n["claims"][3]["issues"]}
    assert n["claims"][0]["citations"][0]["kind"] == "report"  # citations survive to the Advisor
    memo = n["memo"]
    assert n["claims"][0]["text"] in memo
    for bad in ("40%", "99.9", "unattractive"):
        assert bad not in memo


def test_memo_numbers_come_from_the_engine(written):
    memo = written["research"]["narrative"]["memo"]
    assert f"{written['turnover_pct']:.1f}%" in memo
    assert "AI proposed +5.0 pp" in memo and "engine allowed +2.0 pp" in memo


def test_memo_generation_and_flags_are_audited_with_model_and_prompt_version(app, written):
    (memo,) = audit_events(app, written["id"], "memo_generated")
    assert (memo.actor_kind, memo.model, memo.prompt_version) == ("system", "stub-model-1", "recommendation_narrative@v1")
    payload = json.loads(memo.payload_json)
    assert payload["status"] == "complete" and payload["summary"] == {"total": 4, "grounded": 1, "ungrounded": 3}
    assert len(audit_events(app, written["id"], "claim_ungrounded")) == 3
    assert audit_events(app, written["id"], "grounding_checked")


def test_tilt_figures_are_citable_engine_figures(ai):
    ai.approve("equity")
    tilt_for(ai, equity=5.0)
    seen = []

    def reply(p):
        seen.append(p)
        return {"claims": []}

    ai.stub.narrative = reply
    ai.run()
    figures = seen[0]["figures"]
    assert figures["tilt.equity.proposed_pp"] == 5.0 and figures["tilt.equity.allowed_pp"] == 2.0
    assert "turnover_pct" in figures and seen[0]["tilts"][0]["subject"] == "equity"


def test_narrative_failure_keeps_the_recommendation_and_is_audited(app, ai):
    ai.approve("equity")
    tilt_for(ai, equity=2.0)
    ai.stub.narrative = None
    rec = ai.run()
    assert rec["trade_lines"] and rec["research"]["narrative"]["status"] == "failed"
    assert rec["research"]["narrative"]["memo"] is None and rec["research"]["narrative"]["claims"] == []
    (event,) = audit_events(app, rec["id"], "memo_generated")
    assert json.loads(event.payload_json)["status"] == "failed"


def test_no_target_moves_more_than_the_bound_even_when_tilts_stack():
    targets = {"equity": 0.20, "bond": 0.65, "cash": 0.15}
    for tilts in ({"equity": 2.0, "bond": 2.0}, {"equity": 2.0}, {"equity": 2.0, "cash": -2.0}, {"equity": 2.0, "bond": 2.0, "cash": 2.0}):
        out = research_tilt.tilted_targets(targets, tilts, 2.0)
        assert sum(out.values()) == pytest.approx(1.0)
        assert all(abs(out[c] - targets[c]) <= 0.02 + 1e-9 for c in targets), (tilts, out)


def test_a_direction_conflict_is_not_reported_as_a_bound_clip(ai):
    ai.approve("equity")
    tilt_for(ai, equity=-1.0)
    assert entry(ai.run(), "equity")["clipped"] is False
