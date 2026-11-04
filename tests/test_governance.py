"""Seam: the governance page's API (GET /api/governance, POST /api/governance/fixtures/run). Every figure is computed from
stored audit and grounding data; the page is for the Auditor and Platform Owner only."""
import pytest

from tests.conftest import ROLES
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
    check(advisor, rec, [
        {"text": "Tech is favoured.", "citations": [report_cite(rid)]},
        {"text": "Utilities will triple.", "citations": [report_cite(rid, quote="Utilities will triple.")]},
        {"text": "The Portfolio looks fine.", "citations": []},
    ])
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
        card["current_prompt_versions"])


# --- adversarial fixtures: latest run ---------------------------------------------------------------------------------

def test_fixture_results_are_empty_until_a_run_then_reflect_the_latest_run(login):
    assert governance(login)["fixtures"] is None
    auditor = login("auditor")
    first = auditor.post(RUN)
    assert first.status_code == 200, first.text
    run = first.json()
    assert run["total"] >= 4 and run["passed"] == run["total"]  # fabricated quote, wrong number, uncited asset call, ...
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
