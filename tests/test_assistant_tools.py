"""Seam: the Assistant through the HTTP API with a scripted Model. Every read-only lookup is reached the way the model
reaches it, and observed through what the model was handed back, the turn's Trajectory summary and its grounding."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.scripted import ScriptedModel, call, serve
from tests.test_ai_recommendations import ai  # noqa: F401 (imported fixtures)
from tests.test_assistant import answer, ask, model, pending, rec  # noqa: F401 (imported fixtures)
from tests.test_queue import seeded  # noqa: F401 (imported fixtures)

NOT_PERMITTED = "not found or not permitted for your role"
HEALTH: dict = {"kind": "health", "entity_ids": {}, "selected_item": None}
APPROVALS: dict = {"kind": "approvals", "entity_ids": {}, "selected_item": None}
GOVERNANCE: dict = {"kind": "governance", "entity_ids": {}, "selected_item": None}
QUEUE = {"kind": "queue", "entity_ids": {"sort": "score"}, "selected_item": None}


def look_up(app, client, *calls, screen=QUEUE, reply=None):
    """Ask one Question whose first model request makes `calls`; returns (turn, what each tool returned)."""
    script = serve(app, ScriptedModel(list(calls), reply or answer("Looked up.")))
    turn = ask(client, "Look it up", screen).json()
    assert turn["outcome"] == "answered", turn
    return turn, script.requests[1].tool_returns


def tool_steps(turn):
    return [s for s in turn["trajectory"]["steps"] if s["kind"] == "tool_call"]


def test_a_queue_lookup_returns_the_filtered_queue_and_its_totals_ground_claims(app, login, model):
    advisor = login("advisor")
    everything = advisor.get("/api/queue").json()["items"]
    conservative = advisor.get("/api/queue", params={"risk_profile": "conservative"}).json()["items"]
    assert 0 < len(conservative) < len(everything)
    reply = answer("Conservative Portfolios on the Queue")
    reply["claims"] = [
        {
            "text": f"{len(conservative)} Portfolios are conservative.",
            "citations": [{"kind": "engine", "figure": "lookup.1.queue.total_rows"}],
        },
        {  # the screen's own total is still its own figure
            "text": f"{len(everything)} Portfolios are on the Queue.",
            "citations": [{"kind": "engine", "figure": "queue.total_rows"}],
        },
    ]
    turn, returns = look_up(app, advisor, call("look_up_queue", filters={"risk_profile": "conservative"}), reply=reply)
    context = json.loads(returns["look_up_queue"])
    assert context["screen"] == "queue" and context["filters"]["risk_profile"] == "conservative"
    assert [row["portfolio_id"] for row in context["rows"]] == [row["portfolio_id"] for row in conservative]
    assert [c["grounded"] for c in turn["answer"]["claims"]] == [True, True]
    [step] = tool_steps(turn)
    assert step["arguments"] == {"risk_profile": "conservative"}
    assert step["result_summary"] == f"queue: {len(conservative)} rows"


def test_a_queue_lookup_cut_to_the_row_budget_says_how_many_it_shows(app, login, model):
    app.state.settings.assistant_context_rows = 2
    advisor = login("advisor")
    total = len(advisor.get("/api/queue").json()["items"])
    turn, _ = look_up(app, advisor, call("look_up_queue"))
    assert tool_steps(turn)[0]["result_summary"] == f"queue: {total} rows, showing 2"
    assert tool_steps(turn)[0]["arguments"] == {}


def test_a_recommendation_lookup_returns_its_rationale_and_grounds_claims_under_its_portfolio(app, login, rec):
    advisor = login("advisor")
    shown = advisor.get(f"/api/recommendations/{rec.rec['id']}").json()
    breaches = sum(rule["status"] == "breach" for rule in shown["suitability"]["rules"])
    prefix = f"portfolio.{shown['portfolio_id']}.recommendation.{shown['id']}."
    reply = answer("That Recommendation")
    reply["claims"] = [
        {
            "text": f"Turnover is {shown['turnover_pct']}%.",
            "citations": [{"kind": "engine", "figure": prefix + "turnover_pct"}],
        }
    ]
    turn, returns = look_up(
        app, advisor, call("look_up_recommendation", recommendation_id=str(shown["id"])), reply=reply
    )
    assert f'"recommendation_id":{shown["id"]}' in returns["look_up_recommendation"]
    assert "REPORT PASSAGES" in returns["look_up_recommendation"]  # the advisor may read Insights
    assert [c["grounded"] for c in turn["answer"]["claims"]] == [True]
    [step] = tool_steps(turn)
    assert step["arguments"] == {"recommendation_id": str(shown["id"])}
    lines = len(shown["trade_lines"])
    assert step["result_summary"] == (
        f"recommendation {shown['id']}: {lines} trade lines, {breaches} breach{'' if breaches == 1 else 'es'}"
    )


@pytest.mark.parametrize("recommendation_id", ["99999", "²", "9" * 30, "-1"])
def test_a_recommendation_that_does_not_exist_is_not_found_or_not_permitted(app, login, model, recommendation_id):
    turn, returns = look_up(app, login("advisor"), call("look_up_recommendation", recommendation_id=recommendation_id))
    assert returns == {"look_up_recommendation": NOT_PERMITTED}
    assert tool_steps(turn)[0]["result_summary"] == NOT_PERMITTED


def test_an_approvals_lookup_returns_what_waits_on_the_users_decision(app, login, pending):
    committee = login("investment_committee")
    items = committee.get("/api/approvals").json()["items"]
    assert items
    turn, returns = look_up(app, committee, call("look_up_approvals"), screen=APPROVALS)
    context = json.loads(returns["look_up_approvals"])
    assert [i["recommendation_id"] for i in context["items"]] == [i["recommendation"]["id"] for i in items]
    [step] = tool_steps(turn)
    assert step["arguments"] == {} and step["result_summary"] == f"approvals: {len(items)} items"


def test_an_audit_lookup_returns_the_searched_events_and_their_total(app, login, model):
    auditor = login("auditor")
    total = auditor.get("/api/audit/events", params={"type": "priority_scored"}).json()["total"]
    app.state.settings.assistant_context_rows = 3
    assert total > 3
    reply = answer("Priority events")
    reply["claims"] = [
        {"text": f"{total} events.", "citations": [{"kind": "engine", "figure": "lookup.1.audit.total_events"}]}
    ]
    turn, returns = look_up(
        app, auditor, call("look_up_audit", filters={"type": "priority_scored"}), screen=GOVERNANCE, reply=reply
    )
    context = json.loads(returns["look_up_audit"])
    assert {e["type"] for e in context["events"]} == {"priority_scored"} and len(context["events"]) == 3
    assert [c["grounded"] for c in turn["answer"]["claims"]] == [True]
    [step] = tool_steps(turn)
    assert step["arguments"] == {"type": "priority_scored"}
    assert step["result_summary"] == f"audit: {total} events, showing 3"


def test_a_governance_lookup_returns_the_model_card(app, login, model):
    owner = login("platform_owner")
    card = owner.get("/api/governance").json()
    reply = answer("The bound")
    reply["claims"] = [
        {
            "text": f"The tilt bound is {card['model_card']['tilt_bound_pp']} pp.",
            "citations": [{"kind": "engine", "figure": "model_card.tilt_bound_pp"}],
        }
    ]
    turn, returns = look_up(app, owner, call("look_up_governance"), screen=HEALTH, reply=reply)
    assert json.loads(returns["look_up_governance"])["screen"] == "governance"
    assert [c["grounded"] for c in turn["answer"]["claims"]] == [True]
    assert tool_steps(turn)[0]["result_summary"] == "governance: model card"


def test_only_approved_insights_are_listed_with_report_citations_that_ground(app, login, rec):
    rec.approve("Information Technology")
    rejected = rec.analyst.post(f"/api/insights/{rec.ids['Utilities']}/decision", json={"action": "reject"})
    assert rejected.status_code == 200
    advisor = login("advisor")
    listed = advisor.get("/api/insights").json()["items"]
    assert {i["subject"] for i in listed} == {"equity", "Information Technology"}
    it = next(i for i in listed if i["subject"] == "Information Technology")
    report_id, page, passage = it["report_id"], it["page"], it["passage"]
    reply = answer("The approved view")
    reply["claims"] = [
        {
            "text": "Research is positive on Information Technology.",
            "citations": [{"kind": "report", "report_id": report_id, "page": page, "quote": passage}],
        }
    ]
    turn, returns = look_up(
        app,
        advisor,
        call("list_approved_insights"),
        call("list_approved_insights", sector="Information Technology"),
        call("list_approved_insights", sector="Utilities"),
        reply=reply,
    )
    steps = tool_steps(turn)
    assert [s["arguments"] for s in steps] == [{}, {"sector": "Information Technology"}, {"sector": "Utilities"}]
    assert [s["result_summary"] for s in steps] == [
        "insights: 2 approved",
        "insights (Information Technology): 1 approved",
        "insights (Utilities): 0 approved",
    ]
    assert returns["list_approved_insights"] != NOT_PERMITTED  # the latest call: an empty list, not a refusal
    assert json.loads(returns["list_approved_insights"].split("\n\n")[0])["insights"] == []
    assert [c["grounded"] for c in turn["answer"]["claims"]] == [True]


def test_listed_insights_carry_their_passages_fenced_and_never_a_pending_one(app, login, rec):
    turn, returns = look_up(app, login("advisor"), call("list_approved_insights"))
    text = returns["list_approved_insights"]
    context = json.loads(text.split("\n\n")[0])
    assert [i["id"] for i in context["insights"]] == [rec.ids["equity"]]
    assert {"report_id", "page"} <= set(context["insights"][0])
    assert f"<<<REPORT_PASSAGE insight={rec.ids['equity']} " in text
    assert f"insight={rec.ids['Utilities']}" not in text and f"insight={rec.ids['Information Technology']}" not in text


# --- every tool, every role ------------------------------------------------------------------------------------------
# Some roles (a Research Analyst) can open no screen the Assistant is asked from, so the matrix drives the Agent itself,
# with the same deps `ask` gives it.


def run_tools(app, role, calls):
    """Run the Assistant Agent as `role`, its first model request making `calls`; what each tool returned, by name."""
    from sqlalchemy import select

    from app import prompts
    from app.assistant_agent import AssistantDeps, run_agent
    from app.db import User
    from app.llm import LlmRequest

    prompt = prompts.ASSISTANT_ANSWER
    request = LlmRequest(prompt.name, prompt.label, prompt.system, "Question", prompts.ASSISTANT_REPLY_SCHEMA)
    script = ScriptedModel(calls, answer())
    with app.state.session_factory() as db:
        user = db.scalars(select(User).where(User.username == role)).one()
        deps = AssistantDeps(user, db, app.state.market, app.state.settings, {}, [])
        with ThreadPoolExecutor(1) as worker:  # as the app runs it: in a worker thread, outside any event loop
            worker.submit(run_agent, script, request, deps, lambda deps, reply: []).result()
    return script.requests[1].tool_returns


def test_every_tool_for_every_role_is_permitted_exactly_where_its_screen_is_and_never_carries_client_pii(
    app, login, rec
):
    from sqlalchemy import select

    from app.db import ClientRow
    from tests.conftest import ROLES
    from tests.test_recommendations import decide

    advisor = login("advisor")
    assert decide(advisor, rec.rec["id"], "accept").status_code == 200  # an item waits on the Committee
    rejected = rec.analyst.post(f"/api/insights/{rec.ids['Utilities']}/decision", json={"action": "reject"})
    assert rejected.status_code == 200  # Information Technology stays awaiting review
    unreviewed = [rec.ids["Utilities"], rec.ids["Information Technology"]]
    portfolio_id, recommendation_id = rec.rec["portfolio_id"], rec.rec["id"]
    screens = {
        "look_up_queue": ("/api/queue", call("look_up_queue")),
        "look_up_portfolio": (
            f"/api/portfolios/{portfolio_id}",
            call("look_up_portfolio", portfolio_id=portfolio_id),
        ),
        "look_up_recommendation": (
            f"/api/recommendations/{recommendation_id}",
            call("look_up_recommendation", recommendation_id=str(recommendation_id)),
        ),
        "look_up_approvals": ("/api/approvals", call("look_up_approvals")),
        "look_up_audit": ("/api/audit/events", call("look_up_audit")),
        "look_up_governance": ("/api/governance", call("look_up_governance")),
        "list_approved_insights": ("/api/insights", call("list_approved_insights")),
    }
    with app.state.session_factory() as db:
        clients = db.scalars(select(ClientRow)).all()
    forbidden = {c.email for c in clients} | {c.name for c in clients} | {c.name.split()[-1] for c in clients}
    outcomes = set()
    for role in ROLES:
        c = login(role)
        returns = run_tools(app, role, [tool for _, tool in screens.values()])
        assert set(returns) == set(screens)
        for name, (path, _) in screens.items():
            status = c.get(path).status_code
            assert status in (200, 403), (role, path, status)
            assert (returns[name] == NOT_PERMITTED) == (status == 403), (role, name)
            outcomes.add((name, status == 200))
            assert not [f for f in forbidden if f.lower() in str(returns[name]).lower()], (role, name)
        assert not [i for i in unreviewed if f"insight={i} " in returns["list_approved_insights"]], role
        missing = run_tools(
            app,
            role,
            [call("look_up_portfolio", portfolio_id="C999"), call("look_up_recommendation", recommendation_id="99999")],
        )
        assert missing == {"look_up_portfolio": NOT_PERMITTED, "look_up_recommendation": NOT_PERMITTED}
    assert outcomes == {(name, permitted) for name in screens for permitted in (True, False)}  # both, for every tool


LOOKUPS = {
    "look_up_queue",
    "look_up_portfolio",
    "look_up_recommendation",
    "look_up_approvals",
    "look_up_audit",
    "look_up_governance",
    "list_approved_insights",
}


def test_the_model_is_offered_every_lookup_but_the_exchanges_screen_and_the_system_text_describes_each(login, model):
    ask(login("advisor"), "Why?", QUEUE)
    request = model.requests[0]
    assert {tool.name for tool in request.tools} == LOOKUPS
    assert [name for name in sorted(LOOKUPS) if name + "(" not in request.instructions] == []


def test_a_lookup_filter_the_screen_does_not_take_fails_the_turn_without_a_retry(app, login, model):
    script = serve(app, ScriptedModel(call("look_up_queue", filters={"sort": "alphabetical"})))
    turn = ask(login("advisor"), "Look it up", QUEUE).json()
    assert turn["outcome"] == "failed"
    assert len(script.requests) == turn["trajectory"]["requests_used"] == 1
