"""Seam: the Auditor's lineage view of a Recommendation through the HTTP API.

Planted C003 with an approved `equity` Insight and a stub tilt, then fully processed: the Advisor modifies it into a
Suitability breach (version 2), Compliance approves the exception, the Investment Committee approves. Lineage must
reach back from the final Decision to the Report, through every approval step.
"""

import pytest

from app.research_seed import seed_research
from tests.test_ai_recommendations import ai, tilt_for  # noqa: F401  (fixtures)
from tests.test_approvals import act
from tests.test_queue import seeded  # noqa: F401  (fixture)
from tests.test_recommendations import breaching_lines, decide


@pytest.fixture
def processed(ai, login):  # noqa: F811
    ai.approve("equity")
    tilt_for(ai, equity=5.0)
    v1 = ai.run()
    mod = decide(ai.advisor, v1["id"], "modify", "More growth", breaching_lines(ai.advisor, "C003"))
    assert mod.status_code == 200, mod.text
    v2 = mod.json()["recommendation"]
    assert decide(ai.advisor, v2["id"], "accept").status_code == 200
    assert (
        act(login("compliance_officer"), "compliance", v2["id"], "approve", "Client understands the risk").status_code
        == 200
    )
    assert act(login("investment_committee"), "committee", v2["id"], "approve", "Within mandate").status_code == 200
    ai.v1, ai.v2, ai.auditor = v1, v2, login("auditor")
    return ai


def lineage(c, rec_id):
    r = c.get(f"/api/recommendations/{rec_id}/lineage")
    assert r.status_code == 200, r.text
    return r.json()["nodes"]


def types(nodes):
    return [n["type"] for n in nodes]


def test_lineage_runs_from_report_through_every_approval_step_to_the_final_decision(processed):
    nodes = lineage(processed.auditor, processed.v2["id"])
    by_stage = {s: [n["type"] for n in nodes if n["stage"] == s] for s in {n["stage"] for n in nodes}}
    assert "report_ingested" in by_stage["report"]
    assert "insight_approved" in by_stage["insight"]
    assert by_stage["research_tilt"] == ["research_tilt_proposed", "research_tilt_applied"]
    assert {"recommendation_drafted", "recommendation_modified"} <= set(by_stage["recommendation"])
    assert by_stage["decision"] == ["decision_recorded", "decision_recorded", "exception_approved", "decision_recorded"]
    ids = [n["id"] for n in nodes]
    assert ids == sorted(ids), "oldest first"
    assert all(set(n["parent_ids"]) <= set(ids) for n in nodes if n["stage"] != "decision" or n["parent_ids"]), (
        "no dangling parents"
    )


def node(nodes, type, nth=0):
    return [n for n in nodes if n["type"] == type][nth]


def test_every_node_shows_actor_and_timestamp_and_ai_nodes_show_model_and_prompt_version(processed):
    nodes = lineage(processed.auditor, processed.v2["id"])
    assert all(n["actor"]["name"] and n["timestamp"] for n in nodes)
    tilt = node(nodes, "research_tilt_proposed")["actor"]
    assert (tilt["kind"], tilt["model"], tilt["prompt_version"]) == ("system", "stub-model-1", "research_tilt@v1")
    extracted = node(nodes, "insight_extracted")["actor"]
    assert extracted["kind"] == "system" and extracted["model"] and extracted["prompt_version"]
    approval = node(nodes, "insight_approved")["actor"]
    assert (approval["kind"], approval["role"], approval["model"]) == ("user", "research_analyst", None)
    assert node(nodes, "exception_approved")["actor"]["role"] == "compliance_officer"


def test_overrides_are_flagged_and_routine_steps_are_not(processed):
    nodes = lineage(processed.auditor, processed.v2["id"])
    flagged = [(n["type"], n["payload"].get("action")) for n in nodes if n["override"]]
    assert flagged == [
        ("decision_recorded", "modify"),
        ("recommendation_modified", None),
        ("exception_approved", "approve_exception"),
    ]


def test_the_approved_insight_node_carries_its_report_passage(processed):
    n = node(lineage(processed.auditor, processed.v2["id"]), "insight_approved")
    assert n["source"]["report_id"] == processed.report_id
    assert n["source"]["page"] >= 1 and n["source"]["passage"]


def test_only_the_auditor_can_open_lineage_and_unknown_ids_are_404(processed, login):
    rid = processed.v2["id"]
    assert login("advisor").get(f"/api/recommendations/{rid}/lineage").status_code == 403
    assert processed.auditor.get("/api/recommendations/99999/lineage").status_code == 404


def test_human_verified_items_are_marked_and_machine_extracted_ones_are_not(processed):
    nodes = lineage(processed.auditor, processed.v2["id"])
    assert not any(n["human_verified"] for n in nodes), (
        "a freshly uploaded and analyst-approved Report is not human-verified"
    )


def test_seeded_human_verified_report_and_insight_are_marked_in_lineage(ai, app, login):
    assert seed_research(app.state.session_factory) == 5
    ai.stub.tilt = lambda p: {"tilts": [{"insight_id": p["insights"][0]["id"], "impact": "tailwind", "tilt_pp": 1.0}]}
    rec = ai.run()
    nodes = lineage(login("auditor"), rec["id"])
    verified = {n["type"] for n in nodes if n["human_verified"]}
    assert {"report_ingested", "insight_extracted", "insight_approved"} <= verified
