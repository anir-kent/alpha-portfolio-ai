"""Seam: the governance page's API (GET /api/governance, POST /api/governance/fixtures/run). Every figure is computed from
stored audit and grounding data; the page is for the Auditor and Platform Owner only."""

import json
from pathlib import Path

import pytest

from app import prompts
from tests.conftest import ROLES
from tests.fixtures.assistant_eval import EVAL_SET, ScriptedEvalModel, run_eval
from tests.fixtures.suggested_questions import lift_question_limits, seed_demo
from tests.scripted import serve
from tests.test_grounding import check, ctx, report_cite  # noqa: F401  (ctx is a fixture)
from tests.test_queue import seeded  # noqa: F401  (fixture ctx needs)

URL = "/api/governance"
RUN = "/api/governance/fixtures/run"


def governance(login, role="auditor"):
    r = login(role).get(URL)
    assert r.status_code == 200, r.text
    return r.json()


# --- AI quality panel: computed from stored grounding results ---------------------------------------------------------


def test_quality_panel_aggregates_stored_grounding_results(ctx, login):  # noqa: F811
    advisor, rec, rid = ctx
    before = governance(login)["quality"]
    check(
        advisor,
        rec,
        [
            {"text": "Tech is favoured.", "citations": [report_cite(rid)]},
            {"text": "Utilities will triple.", "citations": [report_cite(rid, quote="Utilities will triple.")]},
            {"text": "The Portfolio looks fine.", "citations": []},
        ],
    )
    after = governance(login)["quality"]
    assert after["claims_total"] - before["claims_total"] == 3
    assert after["claims_grounded"] - before["claims_grounded"] == 1
    assert after["claims_ungrounded"] - before["claims_ungrounded"] == 2
    assert after["checks"] - before["checks"] == 1
    by_code = lambda q: {c["code"]: c["count"] for c in q["ungrounded_by_issue"]}  # noqa: E731
    assert by_code(after).get("quote_not_found", 0) - by_code(before).get("quote_not_found", 0) == 1
    assert by_code(after).get("uncited", 0) - by_code(before).get("uncited", 0) == 1
    assert after["pass_rate"] == pytest.approx(after["claims_grounded"] / after["claims_total"])


def test_quality_panel_with_no_grounding_data_has_no_pass_rate(login, app):
    q = governance(login)["quality"]
    assert q["claims_total"] == 0 and q["checks"] == 0 and q["pass_rate"] is None and q["ungrounded_by_issue"] == []


# --- prompt/version log: derived from audit events --------------------------------------------------------------------


def test_prompt_log_lists_each_prompt_version_used_with_when(ctx, login):  # noqa: F811
    from tests.test_research import upload  # the extraction call is logged with its prompt version

    log = {p["prompt_version"]: p for p in governance(login)["prompt_log"]}
    assert "insight_extraction@v1" in log  # ctx uploaded a Report
    entry = log["insight_extraction@v1"]
    assert entry["calls"] >= 1 and entry["models"]
    assert entry["first_used"] <= entry["last_used"]
    upload(login("research_analyst"))
    again = {p["prompt_version"]: p for p in governance(login)["prompt_log"]}["insight_extraction@v1"]
    assert again["calls"] == entry["calls"] + 1 and again["last_used"] >= entry["last_used"]


def test_prompt_log_is_empty_when_no_llm_call_was_made(login, app):
    assert governance(login)["prompt_log"] == []


# --- model card -------------------------------------------------------------------------------------------------------


def test_model_card_reports_configured_model_and_current_prompt_versions(login, settings):
    card = governance(login)["model_card"]
    assert card["model"] == settings.llm_model and card["llm_mode"] == "recorded"
    assert card["tilt_bound_pp"] == 2.0
    assert {"insight_extraction@v1", "research_tilt@v1", "recommendation_narrative@v1", "priority_narrative@v1"} <= set(
        card["current_prompt_versions"]
    )


def test_the_model_card_lists_the_assistant_with_its_prompt_scope_and_limits(login, settings):
    assistant = governance(login)["model_card"]["assistant"]
    assert assistant["prompt_version"] in governance(login)["model_card"]["current_prompt_versions"]
    assert assistant["prompt_version"].startswith("assistant_answer@")
    scope = " ".join(assistant["scope_policy"]).lower()
    assert "investment advice" in scope and "read-only" in scope and "out-of-scope refusal" in scope
    assert assistant["limits"] == {
        "question_max_chars": 2000,
        "questions_per_conversation": 50,
        "questions_per_hour": 20,
        "history_pairs": 6,
        "context_rows": 25,
        "request_limit": 6,
    }


def test_the_model_card_has_no_assistant_eval_results_until_the_live_eval_has_run(login, settings, tmp_path):
    settings.assistant_eval_path = str(tmp_path / "missing.json")
    assert governance(login)["model_card"]["assistant"]["latest_eval"] is None


def test_an_unreadable_eval_results_file_leaves_the_model_card_without_eval_results(login, settings, tmp_path):
    (tmp_path / "old.json").write_text('{"prompt_version": "assistant_answer@v1"}')
    settings.assistant_eval_path = str(tmp_path / "old.json")
    assert governance(login)["model_card"]["assistant"]["latest_eval"] is None


def test_the_model_card_shows_the_latest_live_eval_results(app, login, settings, tmp_path):
    lift_question_limits(settings)
    seed_demo(app)
    serve(app, ScriptedEvalModel(EVAL_SET))
    report = run_eval(app, EVAL_SET, model="scripted-eval-model")
    settings.assistant_eval_path = str(tmp_path / "assistant_eval.json")
    (tmp_path / "assistant_eval.json").write_text(report.model_dump_json())
    latest = governance(login)["model_card"]["assistant"]["latest_eval"]
    assert latest["model"] == "scripted-eval-model" and latest["cases"] == len(EVAL_SET)
    assert latest["refusal_rate"] == 1.0 and latest["ungrounded_claim_rate"] == report.ungrounded_claim_rate
    assert latest["prompt_version"] == governance(login)["model_card"]["assistant"]["prompt_version"]
    assert "results" not in latest  # the card carries the summary; the per-case results stay in the file


@pytest.mark.xfail(
    prompts.ASSISTANT_ANSWER.label == "assistant_answer@v5",
    reason="Live prompt-v5 eval pending: this implementation was explicitly restricted to offline model calls",
    strict=True,
)
def test_the_committed_live_eval_results_are_for_the_current_prompt_version(login):
    # The default settings read the committed results file; a prompt version bump fails this until the live eval
    # (`uv run python -m tests.fixtures.assistant_eval`) is re-run and its results committed.
    assistant = governance(login)["model_card"]["assistant"]
    assert assistant["latest_eval"] is not None, "run the live eval and commit data/assistant_eval.json"
    assert assistant["latest_eval"]["prompt_version"] == assistant["prompt_version"], "re-run the live eval"


def test_governance_preserves_the_committed_live_eval_provenance_and_results(login):
    committed = json.loads((Path(__file__).resolve().parents[1] / "data" / "assistant_eval.json").read_text())
    latest = governance(login)["model_card"]["assistant"]["latest_eval"]
    assert latest is not None
    for field in (
        "prompt_version",
        "model",
        "ran_at",
        "cases",
        "passed",
        "claims_total",
        "refusal_rate",
        "ungrounded_claim_rate",
        "failed_turns",
        "injection_leaks",
    ):
        assert latest[field] == committed[field]


# --- adversarial fixtures: latest run ---------------------------------------------------------------------------------


def test_fixture_results_are_empty_until_a_run_then_reflect_the_latest_run(login):
    assert governance(login)["fixtures"] is None
    auditor = login("auditor")
    first = auditor.post(RUN)
    assert first.status_code == 200, first.text
    run = first.json()
    assert (
        run["total"] >= 4 and run["passed"] == run["total"]
    )  # fabricated quote, wrong number, uncited asset call, ...
    assert {f["name"] for f in run["results"]} >= {"fabricated_quote", "wrong_number", "uncited_asset_call"}
    for f in run["results"]:
        assert f["caught"] is True and set(f["expected_codes"]) <= set(f["actual_codes"])
    assert governance(login)["fixtures"]["run_id"] == run["run_id"]
    second = auditor.post(RUN).json()
    assert second["run_id"] != run["run_id"]
    assert governance(login)["fixtures"]["run_id"] == second["run_id"]


def test_fixture_run_does_not_pollute_quality_figures_and_is_audited(login):
    before = governance(login)["quality"]
    login("platform_owner").post(RUN)
    assert governance(login)["quality"] == before
    events = login("auditor").get("/api/audit/events", params={"type": "adversarial_fixtures_run"}).json()
    assert events["total"] == 1 and events["items"][0]["payload"]["passed"] == events["items"][0]["payload"]["total"]


# --- restricted to permitted roles ------------------------------------------------------------------------------------


@pytest.mark.parametrize("role", ROLES)
def test_governance_is_restricted_to_auditor_and_platform_owner(login, role):
    allowed = role in ("auditor", "platform_owner")
    c = login(role)
    assert (c.get(URL).status_code == 200) is allowed
    assert (c.post(RUN).status_code == 200) is allowed


def test_governance_requires_authentication(client):
    assert client.get(URL).status_code == 401
