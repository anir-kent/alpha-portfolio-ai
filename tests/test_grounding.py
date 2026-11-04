"""Seam: the grounding validator through the HTTP API. Claims are checked against ingested Reports (page + verbatim
quote) and the engine's figures for one Recommendation (ADR-0001). Adversarial claims must be flagged, valid ones pass."""
import json

import pytest
from sqlalchemy import select

from app import grounding
from app.db import AuditEventRow, GroundingResultRow
from tests.test_queue import seeded  # noqa: F401  (fixture)
from tests.test_research import upload

QUOTE = "We are constructive on technology."


@pytest.fixture
def ctx(login, seeded):  # noqa: F811
    advisor = login("advisor")
    assert advisor.post("/api/analysis/runs").status_code == 200
    rec = advisor.get("/api/portfolios/C003").json()["recommendation"]
    report = upload(login("research_analyst")).json()
    return advisor, rec, report["id"]


def check(c, rec, claims):
    r = c.post(f"/api/recommendations/{rec['id']}/grounding", json={"claims": claims})
    assert r.status_code == 200, r.text
    return r.json()


def report_cite(report_id, page=1, quote=QUOTE):
    return {"kind": "report", "report_id": report_id, "page": page, "quote": quote}


def engine_cite(figure):
    return {"kind": "engine", "figure": figure}


def codes(result):
    return {i["code"] for i in result["issues"]}


# --- valid claims pass -------------------------------------------------------------------------------------------

def test_valid_report_and_engine_claims_pass_with_citations_intact(ctx):
    advisor, rec, rid = ctx
    claims = [
        {"text": "The house view is constructive on technology.", "asset": "Information Technology",
         "citations": [report_cite(rid)]},
        {"text": f"Turnover is {rec['turnover_pct']}% of the Portfolio.", "citations": [engine_cite("turnover_pct")]},
    ]
    body = check(advisor, rec, claims)
    assert [r["grounded"] for r in body["results"]] == [True, True]
    assert body["results"][0]["citations"] == claims[0]["citations"]
    assert body["results"][0]["issues"] == []
    assert body["summary"] == {"total": 2, "grounded": 2, "ungrounded": 0}


def test_quote_match_tolerates_whitespace_and_typographic_quotes(ctx):
    advisor, rec, rid = ctx
    quote = "We are  constructive\non technology."
    body = check(advisor, rec, [{"text": "Tech is favoured.", "citations": [report_cite(rid, quote=quote)]}])
    assert body["results"][0]["grounded"] is True


def test_numbers_match_at_the_precision_stated(ctx):
    advisor, rec, rid = ctx
    line = rec["trade_lines"][0]
    text = f"Sell {line['symbol']}: ${line['amount']:,.2f}, {line['pct_of_portfolio']:.1f}% of the Portfolio."
    cites = [engine_cite(f"trade_line.{line['symbol']}.amount"), engine_cite(f"trade_line.{line['symbol']}.pct_of_portfolio")]
    body = check(advisor, rec, [{"text": text, "citations": cites}])
    assert body["results"][0]["grounded"] is True, body["results"][0]["issues"]


# --- adversarial fixtures are caught -----------------------------------------------------------------------------

def test_fabricated_quote_is_flagged(ctx):
    advisor, rec, rid = ctx
    claim = {"text": "Technology will double.", "asset": "Information Technology",
             "citations": [report_cite(rid, quote="Technology will double next year.")]}
    result = check(advisor, rec, [claim])["results"][0]
    assert result["grounded"] is False and codes(result) == {"quote_not_found"}


def test_quote_from_a_different_page_is_flagged(ctx):
    advisor, rec, rid = ctx
    claim = {"text": "Tech.", "citations": [report_cite(rid, page=2)]}
    assert codes(check(advisor, rec, [claim])["results"][0]) == {"quote_not_found"}


def test_unknown_report_and_page_are_flagged(ctx):
    advisor, rec, rid = ctx
    bad_report = {"text": "Tech.", "citations": [report_cite("RPT-nope")]}
    bad_page = {"text": "Tech.", "citations": [report_cite(rid, page=9)]}
    results = check(advisor, rec, [bad_report, bad_page])["results"]
    assert codes(results[0]) == {"report_not_found"} and codes(results[1]) == {"page_not_found"}


def test_wrong_number_is_flagged(ctx):
    advisor, rec, rid = ctx
    wrong = rec["turnover_pct"] + 7
    claim = {"text": f"Turnover is {wrong}% of the Portfolio.", "citations": [engine_cite("turnover_pct")]}
    result = check(advisor, rec, [claim])["results"][0]
    assert result["grounded"] is False and codes(result) == {"number_mismatch"}
    assert str(wrong) in result["issues"][0]["message"]


def test_a_number_with_no_engine_figure_is_flagged_even_when_cited(ctx):
    advisor, rec, rid = ctx
    claim = {"text": "Technology should return 12.5% next year.", "asset": "Information Technology",
             "citations": [report_cite(rid)]}
    assert codes(check(advisor, rec, [claim])["results"][0]) == {"number_mismatch"}


def test_a_number_matching_an_uncited_engine_figure_is_flagged(ctx):
    advisor, rec, rid = ctx
    claim = {"text": f"Turnover is {rec['turnover_pct']}%.", "citations": [engine_cite("total_value")]}
    assert codes(check(advisor, rec, [claim])["results"][0]) == {"number_mismatch"}


def test_uncited_claim_and_uncited_asset_call_are_flagged(ctx):
    advisor, rec, rid = ctx
    plain = {"text": "The Portfolio looks fine.", "citations": []}
    asset_call = {"text": "Buy more energy.", "asset": "Energy", "citations": []}
    engine_only = {"text": "Energy looks good.", "asset": "Energy", "citations": [engine_cite("turnover_pct")]}
    results = check(advisor, rec, [plain, asset_call, engine_only])["results"]
    assert codes(results[0]) == {"uncited"} and codes(results[1]) == {"uncited"}
    assert codes(results[2]) == {"asset_call_needs_report"}
    assert not any(r["grounded"] for r in results)


def test_unknown_engine_figure_is_flagged(ctx):
    advisor, rec, rid = ctx
    claim = {"text": "Alpha is high.", "citations": [engine_cite("alpha_pct")]}
    assert codes(check(advisor, rec, [claim])["results"][0]) == {"unknown_engine_figure"}


# --- flags: visible to the Advisor, kept out of memos, stored, audited -------------------------------------------

def test_ungrounded_claims_stay_visible_but_are_not_memo_eligible(ctx):
    advisor, rec, rid = ctx
    good = {"text": "Tech is favoured.", "citations": [report_cite(rid)]}
    bad = {"text": "Utilities will triple.", "citations": [report_cite(rid, quote="Utilities will triple.")]}
    body = check(advisor, rec, [good, bad])
    assert body["summary"] == {"total": 2, "grounded": 1, "ungrounded": 1}
    assert [r["memo_eligible"] for r in body["results"]] == [True, False]
    fetched = advisor.get(f"/api/recommendations/{rec['id']}/grounding").json()
    assert [r["text"] for r in fetched["results"]] == ["Tech is favoured.", "Utilities will triple."]  # all visible
    assert [r["memo_eligible"] for r in fetched["results"]] == [True, False]


def test_memo_claims_keeps_only_grounded_results():
    ok = grounding.ClaimResult(index=0, text="a", asset=None, citations=[], grounded=True, issues=[])
    bad = grounding.ClaimResult(index=1, text="b", asset=None, citations=[], grounded=False, issues=[])
    assert grounding.memo_claims([ok, bad]) == [ok]


def test_flags_are_recorded_as_audit_events(app, ctx):
    advisor, rec, rid = ctx
    bad = {"text": "Utilities will triple.", "citations": [report_cite(rid, quote="Utilities will triple.")]}
    good = {"text": "Tech is favoured.", "citations": [report_cite(rid)]}
    check(advisor, rec, [good, bad])
    with app.state.session_factory() as db:
        events = list(db.scalars(select(AuditEventRow).where(AuditEventRow.recommendation_id == str(rec["id"]))
                                 .where(AuditEventRow.type.in_(("grounding_checked", "claim_ungrounded")))
                                 .order_by(AuditEventRow.id)))
    checked, flagged = events
    assert checked.type == "grounding_checked" and checked.client_id == "C003" and checked.actor_kind == "system"
    assert json.loads(checked.payload_json)["summary"] == {"total": 2, "grounded": 1, "ungrounded": 1}
    assert flagged.type == "claim_ungrounded" and json.loads(flagged.parent_ids_json) == [checked.id]
    payload = json.loads(flagged.payload_json)
    assert payload["text"] == "Utilities will triple." and payload["issues"][0]["code"] == "quote_not_found"


def test_results_are_stored_for_later_aggregation(app, ctx):
    advisor, rec, rid = ctx
    check(advisor, rec, [{"text": "x", "citations": []}, {"text": "Tech.", "citations": [report_cite(rid)]}])
    with app.state.session_factory() as db:
        rows = list(db.scalars(select(GroundingResultRow).order_by(GroundingResultRow.id)))
    assert [r.grounded for r in rows] == [False, True]
    assert rows[0].recommendation_id == rec["id"] and rows[0].client_id == "C003"
    assert json.loads(rows[0].issues_json)[0]["code"] == "uncited"
    assert len({r.check_id for r in rows}) == 1


def test_get_returns_the_latest_check_only(ctx):
    advisor, rec, rid = ctx
    check(advisor, rec, [{"text": "old", "citations": []}])
    check(advisor, rec, [{"text": "new", "citations": [report_cite(rid)]}])
    assert [r["text"] for r in advisor.get(f"/api/recommendations/{rec['id']}/grounding").json()["results"]] == ["new"]


def test_get_before_any_check_is_empty(ctx):
    advisor, rec, rid = ctx
    body = advisor.get(f"/api/recommendations/{rec['id']}/grounding").json()
    assert body["results"] == [] and body["summary"] == {"total": 0, "grounded": 0, "ungrounded": 0}


def test_unknown_recommendation_is_404(ctx):
    advisor, rec, rid = ctx
    assert advisor.post("/api/recommendations/9999/grounding", json={"claims": []}).status_code == 404


@pytest.mark.parametrize("role,validate,read", [
    ("advisor", True, True), ("relationship_manager", True, True), ("auditor", False, True),
    ("compliance_officer", False, True), ("research_analyst", False, False), ("platform_owner", False, False),
])
def test_permissions(login, ctx, role, validate, read):
    advisor, rec, rid = ctx
    c = login(role)
    assert (c.post(f"/api/recommendations/{rec['id']}/grounding", json={"claims": []}).status_code == 200) is validate
    assert (c.get(f"/api/recommendations/{rec['id']}/grounding").status_code == 200) is read
