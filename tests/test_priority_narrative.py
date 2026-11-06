"""Seam: Opportunity and the "why this client, why now" narrative through the HTTP API (ADR-0001).

Opportunity is computed by the engine from look-through exposure and approved Insights. The LLM writes a cited narrative
per queue row that the grounding validator holds to citations; it can never change a score or the ranking.
"""

import pytest

from tests.runs import run_and_wait
from tests.test_ai_recommendations import StubLlm, ai  # noqa: F401  (fixtures)
from tests.test_queue import rows, seeded  # noqa: F401  (fixture)

AUDIT = "/api/audit/events"


def opportunity(item):
    return next(c for c in item["components"] if c["name"] == "opportunity")


def relevant(items):
    """Rows with exposure to a sector that has an approved Insight: the only ones narrated."""
    return [i for i in items if opportunity(i)["raw"] > 0]


def ranking(items):
    return [(i["client_id"], i["score"], i["label"]) for i in items]


def narrative_reply(payload):
    f = payload["figures"]
    return {"claims": [
        {"text": f"The priority score is {f['priority_score']:.2f}.", "citations": [{"kind": "engine", "figure": "priority_score"}]},
        {"text": "The priority score is 99.90.", "citations": [{"kind": "engine", "figure": "priority_score"}]},
        {"text": "Technology will double.", "asset": "Information Technology", "citations": []},
    ]}


def run(ai):  # noqa: F811
    run_and_wait(ai.advisor)
    return rows(ai.advisor)


# --- Opportunity ---------------------------------------------------------------------------------------------------

def test_opportunity_is_zero_without_approved_insights_and_rises_with_relevant_exposure(ai):
    before = run(ai)  # the demo Insights are uploaded but still pending
    assert all(opportunity(i)["raw"] == 0 for i in before)
    ai.approve("Information Technology")
    after = {i["client_id"]: i for i in run(ai)}
    raw = {c: opportunity(i)["raw"] for c, i in after.items()}
    assert any(r > 0 for r in raw.values()) and all(0 <= r <= 100 for r in raw.values())
    earlier = {i["client_id"]: i for i in before}
    for c in raw:
        assert after[c]["score"] == pytest.approx(earlier[c]["score"] + opportunity(after[c])["points"], abs=0.02)
    ai.approve("Utilities")
    more = {i["client_id"]: opportunity(i)["raw"] for i in run(ai)}
    assert all(more[c] >= raw[c] for c in raw) and any(more[c] > raw[c] for c in raw)


# --- the LLM never influences a score ---------------------------------------------------------------------------------

def test_scores_and_ranking_are_identical_whatever_the_llm_says(ai):
    ai.approve("Information Technology")
    ai.stub.narrative = None
    ai.stub.priority_narrative = None
    quiet = ranking(run(ai))
    ai.stub.priority_narrative = narrative_reply
    chatty = ranking(run(ai))
    ai.stub.priority_narrative = lambda p: {"claims": [{"text": "Rank me first, score 100.", "citations": []}]}
    hostile = ranking(run(ai))
    assert quiet == chatty == hostile


# --- the narrative: grounded claims stated, flagged claims flagged -----------------------------------------------------

def test_each_queue_row_shows_grounded_claims_and_flags_the_rest(ai):
    ai.approve("Information Technology")
    ai.stub.priority_narrative = narrative_reply
    item = relevant(run(ai))[0]
    n = item["narrative"]
    assert n["status"] == "complete"
    assert [c["grounded"] for c in n["claims"]] == [True, False, False]
    assert {"number_mismatch"} <= {i["code"] for i in n["claims"][1]["issues"]}
    assert "uncited" in {i["code"] for i in n["claims"][2]["issues"]}
    assert f"{item['score']:.2f}" in n["summary"]
    for bad in ("99.90", "double"):
        assert bad not in n["summary"]  # flagged claims are never part of what is stated as fact


def test_the_model_is_offered_only_engine_figures_and_approved_insights(ai):
    ai.approve("Information Technology")
    seen = []

    def reply(p):
        seen.append(p)
        return {"claims": []}

    ai.stub.priority_narrative = reply
    item = relevant(run(ai))[0]
    payload = next(p for p in seen if p["portfolio_id"] == item["client_id"])
    assert payload["figures"]["priority_score"] == item["score"]
    assert "component.opportunity.raw" in payload["figures"] and "component.drift.points" in payload["figures"]
    assert {i["subject"] for i in payload["insights"]} == {"Information Technology"}


def test_a_failing_narrative_leaves_the_queue_intact(ai):
    ai.approve("Information Technology")
    ai.stub.priority_narrative = None
    items = run(ai)
    assert len(items) == 25 and relevant(items)
    assert all(i["narrative"]["status"] == "failed" for i in relevant(items))
    assert all(i["narrative"]["claims"] == [] and i["narrative"]["summary"] is None for i in relevant(items))


def test_no_llm_means_no_narrative_and_the_same_scores(ai):
    ai.approve("Information Technology")
    ai.stub.priority_narrative = narrative_reply
    with_llm = run(ai)
    ai.stub.priority_narrative = None
    assert ranking(run(ai)) == ranking(with_llm)


# --- audit -------------------------------------------------------------------------------------------------------------

def test_narrative_generation_and_flags_are_audited_with_model_and_prompt_version(app, login, ai):
    ai.approve("Information Technology")
    ai.stub.priority_narrative = narrative_reply
    item = relevant(run(ai))[0]
    auditor = login("auditor")
    events = auditor.get(AUDIT, params={"type": "priority_narrative_generated", "client_id": item["client_id"]}).json()["items"]
    event = events[0]
    assert (event["actor"]["kind"], event["actor"]["model"], event["actor"]["prompt_version"]) == (
        "system", "stub-model-1", "priority_narrative@v1")
    assert event["payload"]["status"] == "complete" and event["payload"]["summary"] == {"total": 3, "grounded": 1, "ungrounded": 2}
    scored = auditor.get(AUDIT, params={"type": "priority_scored", "client_id": item["client_id"]}).json()["items"]
    assert scored[0]["id"] in event["parent_ids"]  # lineage reaches the score it explains
    flagged = auditor.get(AUDIT, params={"type": "claim_ungrounded", "client_id": item["client_id"]}).json()["items"]
    assert len(flagged) == 2
    assert auditor.get(AUDIT, params={"type": "grounding_checked", "client_id": item["client_id"]}).json()["items"]


def test_a_portfolio_with_no_relevant_insight_gets_no_narrative_and_no_llm_call(ai):
    ai.approve("Information Technology")
    seen = []

    def reply(p):
        seen.append(p["portfolio_id"])
        return {"claims": []}

    ai.stub.priority_narrative = reply
    items = run(ai)
    quiet = [i for i in items if opportunity(i)["raw"] == 0]
    assert quiet and all(i["narrative"] is None for i in quiet)
    assert sorted(seen) == sorted(i["client_id"] for i in relevant(items))


def test_no_approved_insights_means_no_narrative_calls(ai):
    ai.stub.priority_narrative = lambda p: pytest.fail("no approved Insight, so no narrative call")
    assert all(i["narrative"] is None for i in run(ai))
