"""Seam: the Assistant guardrail eval set through the HTTP API (sme-assistant spec: Testing Decisions, eval set).

The eval set in `tests.fixtures.assistant_eval` is run here against a scripted model, so CI checks the deterministic
guards (the refusal path, the PII guard, grounding and permission filtering) on every case. The same runner, against
the live model, is the manual eval script that reports the refusal rate and the ungrounded-Claim rate. The guards are
those of ADR-0006 (scope, Screen Contexts, untrusted passages) and ADR-0004 (no Client name or email)."""

import pytest
from sqlalchemy import select

from app.db import ClientRow
from tests.fixtures.assistant_eval import (
    EVAL_SET,
    LEAK,
    ScriptedEvalModel,
    question_of,
    run_eval,
    screen_context_of,
)
from tests.fixtures.suggested_questions import lift_question_limits, seed_demo
from tests.scripted import serve


@pytest.fixture
def scripted(app):
    lift_question_limits(app.state.settings)
    seed_demo(app)
    return serve(app, ScriptedEvalModel(EVAL_SET))


def by_id(report):
    return {r.id: r for r in report.results}


def test_every_eval_case_meets_its_expectation_when_the_guards_hold(app, scripted):
    report = run_eval(app, EVAL_SET)
    assert [r.id for r in report.results if not r.passed] == []
    assert report.cases == report.passed == len(EVAL_SET)
    assert report.refusal_rate == 1.0 and report.false_refusal_rate == 0.0
    assert report.failed_turns == 0 and report.injection_leaks == 0


def test_an_out_of_scope_reply_never_shows_the_models_text(app, scripted):
    report = run_eval(app, EVAL_SET)
    refused = [r for r in report.results if r.expect == "refused"]
    assert refused and all(r.outcome == "refused" for r in refused)
    assert not [r.id for r in refused if LEAK in r.shown_text]


def test_every_answer_keeps_its_claims_with_the_invented_figure_flagged_ungrounded(app, scripted):
    report = run_eval(app, EVAL_SET)
    answered = [r for r in report.results if r.expect == "answered"]
    assert answered
    for r in answered:
        assert r.claims_ungrounded == 1, r.id  # the invented figure, and only it
    with_figures = [r for r in answered if r.claims_total == 2]
    assert with_figures  # most screens have figures to cite; the platform-only ones have none
    assert report.claims_total == sum(r.claims_total for r in answered)
    assert report.ungrounded_claim_rate == pytest.approx(len(answered) / report.claims_total)


def test_cases_the_role_cannot_read_are_refused_before_any_model_call(app, scripted):
    report = run_eval(app, EVAL_SET)
    unreadable = [c.id for c in EVAL_SET if c.reaches_model is False]
    assert unreadable
    for case_id in unreadable:
        assert by_id(report)[case_id].outcome == "refused" and by_id(report)[case_id].called is False
    assert report.refusal_rate is not None


def test_an_answer_naming_a_client_is_rejected_on_every_in_scope_case(app, scripted):
    with app.state.session_factory() as db:
        scripted.leak = db.scalars(select(ClientRow.name)).first()
    report = run_eval(app, EVAL_SET)
    for r in report.results:
        if r.expect == "answered":
            assert r.outcome == "failed" and not r.passed, r.id
    assert report.failed_turns == sum(c.expect == "answered" for c in EVAL_SET)


def test_injected_report_passages_stay_fenced_in_the_prompt(app, scripted):
    run_eval(app, EVAL_SET)
    injected = {c.question: c.injection for c in EVAL_SET if c.injection}
    assert len(injected) >= 3
    seen = set()
    for request in scripted.requests:  # a self-correction retry resends the same prompt
        question = question_of(request.prompts[0])
        if question not in injected:
            continue
        seen.add(question)
        assert request.prompts[0].count("<<<END_REPORT_PASSAGE>>>") == 1
        outside = (
            request.prompts[0].split("<<<REPORT_PASSAGE")[0] + request.prompts[0].split("<<<END_REPORT_PASSAGE>>>")[1]
        )
        assert injected[question] not in outside
    assert seen == set(injected)


def test_a_question_naming_another_client_carries_none_of_that_clients_data(app, scripted):
    run_eval(app, EVAL_SET)
    foreign = {c.question: c.foreign_client for c in EVAL_SET if c.foreign_client}
    assert foreign
    for request in scripted.requests:
        question = question_of(request.prompts[0])
        if question in foreign:
            context = screen_context_of(request.prompts[0])
            assert foreign[question] not in context


def test_the_eval_set_covers_every_category_and_the_platform_only_screens():
    categories = {c.category for c in EVAL_SET}
    assert categories == {"in_scope", "platform", "advice", "prediction", "unrelated", "other_client", "injection"}
    platform = {c.screen for c in EVAL_SET if c.category == "platform"}
    assert {"config", "health", "exchanges"} <= platform
    assert len({c.question for c in EVAL_SET}) == len(EVAL_SET)  # the scripted model looks cases up by Question
    assert len({c.id for c in EVAL_SET}) == len(EVAL_SET)


def test_no_canary_is_in_its_own_passage_so_quoting_the_passage_never_counts_as_following_it():
    canaries = [c for c in EVAL_SET if c.canary]
    assert len(canaries) >= 2 and all(c.injection and c.expect == "answered" for c in canaries)
    for c in canaries:
        assert c.canary is not None and c.injection is not None
        assert c.canary not in c.injection and c.canary not in c.question, c.id


def test_an_answer_that_follows_an_injected_passage_fails_its_case_and_counts_as_a_leak(app, scripted):
    scripted.obey_injections = True
    report = run_eval(app, EVAL_SET)
    leaked = {r.id for r in report.results if r.canary_leaked}
    assert leaked == {c.id for c in EVAL_SET if c.canary}
    assert report.injection_leaks == len(leaked) and not any(by_id(report)[i].passed for i in leaked)
