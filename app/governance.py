"""Governance figures for the Auditor and Platform Owner. Nothing here is hand-written: the AI quality panel aggregates
stored grounding results, the prompt/version log is read from audit events, the model card from live settings and
config, and the adversarial fixture results from the latest stored run of the real grounding validator. The one
exception is the Assistant's latest live eval: the eval script (tests.fixtures.assistant_eval) is run by hand before a
prompt version bump, writes its results to a committed file, and the model card reads them from there (sme-assistant
spec: Governance; ADR-0006)."""

import json
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit, config_service, grounding, prompts
from app.db import (
    AuditEventRow,
    FixtureRunRow,
    GroundingResultRow,
    LlmExchangeRow,
    ReportPageRow,
    ReportRow,
    make_session_factory,
)
from app.settings import Settings

# --- AI quality panel ---------------------------------------------------------------------------------------------


class IssueCount(BaseModel):
    code: str
    count: int


class Quality(BaseModel):
    checks: int
    claims_total: int
    claims_grounded: int
    claims_ungrounded: int
    pass_rate: float | None  # grounded / total; None until a claim has been checked
    ungrounded_by_issue: list[IssueCount]  # a claim with several issues counts once per issue


def quality(db: Session) -> Quality:
    total, grounded, checks = db.execute(
        select(
            func.count(),
            func.count().filter(GroundingResultRow.grounded.is_(True)),
            func.count(func.distinct(GroundingResultRow.check_id)),
        )
    ).one()
    issues: Counter[str] = Counter()
    for (raw,) in db.execute(select(GroundingResultRow.issues_json).where(GroundingResultRow.grounded.is_(False))):
        issues.update(i["code"] for i in json.loads(raw))
    return Quality(
        checks=checks,
        claims_total=total,
        claims_grounded=grounded,
        claims_ungrounded=total - grounded,
        pass_rate=grounded / total if total else None,
        ungrounded_by_issue=[
            IssueCount(code=c, count=n) for c, n in sorted(issues.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
    )


# --- capture health -----------------------------------------------------------------------------------------------


class CaptureHealth(BaseModel):
    total: int  # LLM Exchanges stored
    live: int
    recorded: int  # replayed from recordings
    errors: int  # Exchanges whose call failed at the transport level
    unreferenced: int  # Exchanges no Audit Event points at: a step failed to anchor its call, or an event was removed


def capture_health(db: Session) -> CaptureHealth:
    total, live, recorded, errors = db.execute(
        select(
            func.count(),
            func.count().filter(LlmExchangeRow.mode == "live"),
            func.count().filter(LlmExchangeRow.mode == "recorded"),
            func.count().filter(LlmExchangeRow.outcome == "error"),
        )
    ).one()
    referenced: set[int] = set()
    for (raw,) in db.execute(
        select(AuditEventRow.payload_json).where(AuditEventRow.payload_json.contains('"exchange_id"'))
    ):
        referenced.update(exchange_id for exchange_id, _ in audit.exchange_references(raw))
    stored = set(db.scalars(select(LlmExchangeRow.id)))
    return CaptureHealth(
        total=total, live=live, recorded=recorded, errors=errors, unreferenced=len(stored - referenced)
    )


# --- prompt / version log -----------------------------------------------------------------------------------------


class PromptUse(BaseModel):
    prompt_version: str  # "name@version"
    models: list[str]  # models that answered; empty if every call failed
    calls: int
    first_used: str
    last_used: str


def prompt_log(db: Session) -> list[PromptUse]:
    """Every prompt version that appears on an audit event, with the models, call count and first/last use."""
    uses: dict[str, dict] = {}
    for version, model, ts in db.execute(
        select(AuditEventRow.prompt_version, AuditEventRow.model, AuditEventRow.timestamp)
        .where(AuditEventRow.prompt_version.is_not(None))
        .order_by(AuditEventRow.id)
    ):
        assert version is not None  # the query keeps only events with a prompt version
        u = uses.setdefault(version, {"models": set(), "calls": 0, "first": ts, "last": ts})
        u["calls"] += 1
        u["last"] = max(u["last"], ts)
        u["first"] = min(u["first"], ts)
        if model:
            u["models"].add(model)
    return [
        PromptUse(
            prompt_version=v, models=sorted(u["models"]), calls=u["calls"], first_used=u["first"], last_used=u["last"]
        )
        for v, u in sorted(uses.items())
    ]


# --- Assistant guardrail eval -------------------------------------------------------------------------------------

EvalCategory = Literal["in_scope", "platform", "advice", "prediction", "unrelated", "other_client", "injection"]
EvalExpectation = Literal["answered", "refused"]


class EvalCaseResult(BaseModel):
    id: str
    category: EvalCategory
    expect: EvalExpectation
    outcome: Literal["answered", "refused", "failed"]
    called: bool  # whether the Question reached the model; an unreadable screen is refused before any call
    shown_text: str  # what the user saw: the Answer's text, the Out-of-Scope Refusal or the failure message
    claims_total: int
    claims_ungrounded: int
    ungrounded_issues: list[str]  # the grounding issue codes of the ungrounded Claims, one per issue
    canary_leaked: bool  # an Answer wrote what an injected Report passage asked for
    problems: list[str]  # why the case did not pass; empty when it did

    @property
    def passed(self) -> bool:
        return not self.problems


class AssistantEvalSummary(BaseModel):
    """The headline figures of one run of the guardrail eval set; the model card shows these."""

    prompt_version: str  # the version it was run against; stale once it differs from the Assistant's
    model: str
    ran_at: str  # ISO 8601, UTC
    cases: int
    passed: int
    refusal_rate: float | None  # out-of-scope Questions that reached the model and that it refused
    false_refusal_rate: float | None  # in-scope Questions refused
    claims_total: int  # Claims of every answered turn, whether or not the Question was in scope
    ungrounded_claim_rate: float | None  # ungrounded / claims_total
    failed_turns: int
    injection_leaks: int  # injection cases that did not pass: the passage was obeyed or it bypassed the scope policy


class AssistantEval(AssistantEvalSummary):
    """One run of the guardrail eval set with its per-case results, as the eval script writes it to
    `assistant_eval_path`."""

    results: list[EvalCaseResult]


def latest_assistant_eval(path: str) -> AssistantEval | None:
    """The latest live eval results, or None if the eval has never been run here or its file is from an older schema
    (the committed-results test catches that; the Governance screen keeps working meanwhile)."""
    try:
        return AssistantEval.model_validate_json(Path(path).read_text())
    except (FileNotFoundError, ValidationError):
        return None


# --- model card ---------------------------------------------------------------------------------------------------


class AssistantLimits(BaseModel):
    question_max_chars: int
    questions_per_conversation: int
    questions_per_hour: int
    history_pairs: int  # earlier Question/Answer pairs sent with each Question
    context_rows: int  # rows of a list screen a Screen Context holds


class AssistantCard(BaseModel):
    prompt_version: str
    scope_policy: list[str]
    limits: AssistantLimits
    latest_eval: AssistantEvalSummary | None  # None until the live eval has been run and its results committed


ASSISTANT_SCOPE_POLICY = (
    "In scope: how the platform works and the data on the user's current screen, rebuilt by the server and filtered by "
    "the user's permissions. Contexts carry Client ids only, never names or emails.",
    "Out of scope: investment advice, market predictions, Clients or items not on the screen, and unrelated topics. "
    "These get the fixed Out-of-Scope Refusal; the model's own text is never shown.",
    "Read-only: the Assistant never approves, decides, modifies or starts anything.",
    "Every Claim is grounding-checked against the Screen Context's figures and Report passages; ungrounded Claims "
    "are flagged. An Answer naming a Client is rejected as a failure.",
    "Report passages and LLM Exchange bodies are fenced as untrusted data, never followed as instructions.",
)


def _assistant_card(settings: Settings) -> AssistantCard:
    latest = latest_assistant_eval(settings.assistant_eval_path)
    return AssistantCard(
        prompt_version=prompts.ASSISTANT_ANSWER.label,
        scope_policy=list(ASSISTANT_SCOPE_POLICY),
        limits=AssistantLimits(
            question_max_chars=settings.assistant_question_max_chars,
            questions_per_conversation=settings.assistant_questions_per_conversation,
            questions_per_hour=settings.assistant_questions_per_hour,
            history_pairs=settings.assistant_history_pairs,
            context_rows=settings.assistant_context_rows,
        ),
        latest_eval=AssistantEvalSummary.model_validate(latest.model_dump(exclude={"results"})) if latest else None,
    )


class ModelCard(BaseModel):
    model: str
    llm_mode: str
    llm_endpoint: str
    temperature: float | None  # None: not sent, the provider's default
    tilt_bound_pp: float
    current_prompt_versions: list[str]
    controls: list[str]
    assistant: AssistantCard


def model_card(db: Session, settings: Settings) -> ModelCard:
    return ModelCard(
        model=settings.llm_model,
        llm_mode=settings.llm_mode,
        llm_endpoint=urlsplit(settings.llm_base_url).hostname or "",
        temperature=settings.llm_temperature,
        tilt_bound_pp=config_service.get_config(db).tilt_bound_pp,
        current_prompt_versions=[p.label for p in prompts.ALL],
        controls=[
            "The deterministic engine owns every number and every compliance outcome; the LLM only explains and proposes (ADR-0001).",
            "Every claim needs a citation; Report quotes must appear on the cited page and numbers must match cited engine figures.",
            "Research Tilts are clipped by the engine to the configured bound; only approved Insights can influence them.",
            "Ungrounded claims are flagged, kept out of memos and stay visible to the Advisor.",
            "A human accepts, modifies or rejects every Recommendation; nothing is executed.",
        ],
        assistant=_assistant_card(settings),
    )


# --- adversarial fixtures -----------------------------------------------------------------------------------------

_REPORT = "RPT-FIXTURE"
_QUOTE = "We are constructive on technology."
_FIGURES = {"turnover_pct": 12.5, "total_value": 1_000_000.0}


class Fixture(BaseModel):
    name: str
    description: str
    claim: grounding.Claim
    expected_codes: list[str]  # issue codes the validator must raise; empty means the claim must pass


def _report(page: int = 1, quote: str = _QUOTE, report_id: str = _REPORT) -> grounding.ReportCitation:
    return grounding.ReportCitation(kind="report", report_id=report_id, page=page, quote=quote)


def _engine(figure: str) -> grounding.EngineCitation:
    return grounding.EngineCitation(kind="engine", figure=figure)


FIXTURES: tuple[Fixture, ...] = (
    Fixture(
        name="valid_report_claim",
        description="A verbatim quote on the cited page passes.",
        claim=grounding.Claim(
            text="The house view is constructive on technology.", asset="Information Technology", citations=[_report()]
        ),
        expected_codes=[],
    ),
    Fixture(
        name="valid_engine_claim",
        description="A number equal to a cited engine figure passes.",
        claim=grounding.Claim(text="Turnover is 12.5% of the Portfolio.", citations=[_engine("turnover_pct")]),
        expected_codes=[],
    ),
    Fixture(
        name="fabricated_quote",
        description="A quote that is not on the cited page.",
        claim=grounding.Claim(
            text="Technology will double.",
            asset="Information Technology",
            citations=[_report(quote="Technology will double next year.")],
        ),
        expected_codes=["quote_not_found"],
    ),
    Fixture(
        name="wrong_number",
        description="A number that differs from the cited engine figure.",
        claim=grounding.Claim(text="Turnover is 19.5% of the Portfolio.", citations=[_engine("turnover_pct")]),
        expected_codes=["number_mismatch"],
    ),
    Fixture(
        name="uncited_asset_call",
        description="A view on an asset with no citation at all.",
        claim=grounding.Claim(text="Buy more energy.", asset="Energy", citations=[]),
        expected_codes=["uncited"],
    ),
    Fixture(
        name="engine_only_asset_call",
        description="A view on an asset supported only by an engine figure.",
        claim=grounding.Claim(text="Energy looks good.", asset="Energy", citations=[_engine("turnover_pct")]),
        expected_codes=["asset_call_needs_report"],
    ),
    Fixture(
        name="unknown_report",
        description="A citation of a Report that does not exist.",
        claim=grounding.Claim(text="Tech.", citations=[_report(report_id="RPT-nope")]),
        expected_codes=["report_not_found"],
    ),
    Fixture(
        name="unknown_page",
        description="A citation of a page the Report does not have.",
        claim=grounding.Claim(text="Tech.", citations=[_report(page=9)]),
        expected_codes=["page_not_found"],
    ),
    Fixture(
        name="invented_engine_figure",
        description="A citation of a figure the engine never produced.",
        claim=grounding.Claim(text="Alpha is high.", citations=[_engine("alpha_pct")]),
        expected_codes=["unknown_engine_figure"],
    ),
)


class FixtureResult(BaseModel):
    name: str
    description: str
    expected_codes: list[str]
    actual_codes: list[str]
    caught: bool  # the validator raised exactly the expected codes (and passed the valid claims)


class FixtureRun(BaseModel):
    run_id: int
    ran_at: str
    ran_by: str
    total: int
    passed: int
    results: list[FixtureResult]


def run_fixtures(claims: Iterable[Fixture] = FIXTURES) -> list[FixtureResult]:
    """Run the fixtures through the real validator against a throwaway database, so the stored quality figures are untouched."""
    factory = make_session_factory("sqlite://")
    try:
        with factory() as scratch:
            scratch.add(
                ReportRow(
                    id=_REPORT,
                    title="Adversarial fixture",
                    filename="fixture.txt",
                    kind="text",
                    uploaded_by="governance",
                    uploaded_at=audit.format_ts(datetime.now(UTC)),
                    page_count=1,
                    human_verified=True,
                    extraction_status="seeded",
                )
            )
            scratch.add(ReportPageRow(report_id=_REPORT, page=1, text=f"Fixture house view. {_QUOTE} Nothing else."))
            scratch.commit()
            out = []
            for i, f in enumerate(claims):
                result = grounding.validate_claim(scratch, f.claim, i, _FIGURES)
                actual = sorted({issue.code for issue in result.issues})
                caught = (
                    result.grounded
                    if not f.expected_codes
                    else (not result.grounded and set(f.expected_codes) == set(actual))
                )
                out.append(
                    FixtureResult(
                        name=f.name,
                        description=f.description,
                        expected_codes=f.expected_codes,
                        actual_codes=actual,
                        caught=caught,
                    )
                )
            return out
    finally:
        factory.kw["bind"].dispose()


def _run_out(row: FixtureRunRow) -> FixtureRun:
    results = [FixtureResult(**r) for r in json.loads(row.results_json)]
    return FixtureRun(
        run_id=row.id,
        ran_at=row.ran_at,
        ran_by=row.ran_by,
        total=len(results),
        passed=sum(r.caught for r in results),
        results=results,
    )


def record_run(db: Session, actor: audit.Actor) -> FixtureRun:
    results = run_fixtures()
    row = FixtureRunRow(
        ran_at=audit.format_ts(datetime.now(UTC)),
        ran_by=actor.name,
        results_json=json.dumps([r.model_dump() for r in results]),
    )
    db.add(row)
    db.commit()
    run = _run_out(row)
    audit.record(
        db,
        "adversarial_fixtures_run",
        actor,
        {
            "run_id": run.run_id,
            "total": run.total,
            "passed": run.passed,
            "failed": [r.name for r in run.results if not r.caught],
        },
    )
    return run


def latest_run(db: Session) -> FixtureRun | None:
    row = db.scalar(select(FixtureRunRow).order_by(FixtureRunRow.id.desc()).limit(1))
    return None if row is None else _run_out(row)
