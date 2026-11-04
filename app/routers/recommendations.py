import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import approvals, audit, grounding, recommendations
from app.config_service import Config, get_config
from app.db import DecisionRow, RecommendationNarrativeRow, RecommendationRow, RecommendationTiltRow, User
from app.deps import get_db, get_market, require
from app.market_data import MarketData
from app.rebalance import TradeLine
from app.routers.analysis import ClassDriftOut, RuleOut
from app.routers.grounding import ClaimResultOut

router = APIRouter(prefix="/api", tags=["recommendations"])

Status = Literal["pending_advisor", "pending_compliance", "pending_committee", "approved", "rejected", "superseded"]
Step = Literal["advisor", "compliance", "committee"]
Rule = Literal["pass", "warning", "breach"]


class TradeLineOut(BaseModel):
    account_id: str
    symbol: str
    name: str
    side: Literal["buy", "sell"]
    quantity: int
    price: float
    currency: str
    amount: float
    pct_of_portfolio: float


class PostTradeSuitability(BaseModel):
    status: Rule  # worst rule status on the post-trade Portfolio
    rules: list[RuleOut]


class ThresholdsOut(BaseModel):
    turnover_pct: float
    trade_line_pct: float


class ApprovalOut(BaseModel):
    """Which approval steps this Recommendation needs, and why (thresholds are those currently configured)."""

    required_steps: list[Step]
    needs_compliance: bool  # a Suitability Rule is in breach
    high_impact: bool  # turnover or a single Trade Line is at or above a threshold
    thresholds: ThresholdsOut
    reasons: list[str]  # why it is high-impact


class TiltEntryOut(BaseModel):
    subject_kind: Literal["sector", "asset_class"]
    subject: str
    exposure_pct: float  # look-through share of the Portfolio, from the engine
    proposed_pp: float  # what the AI proposed
    allowed_pp: float  # what the engine allowed after bounds and direction checks
    clipped: bool
    reason: str
    insight_ids: list[int]


class TiltOut(BaseModel):
    status: Literal["ok", "failed"]  # failed: the plain rule-based Recommendation stands
    bound_pp: float
    model: str | None
    prompt_version: str
    error: str | None
    entries: list[TiltEntryOut]


class NarrativeOut(BaseModel):
    status: Literal["complete", "failed"]
    model: str | None
    prompt_version: str | None
    error: str | None
    memo: str | None  # built only from grounded claims plus engine figures
    claims: list[ClaimResultOut]  # every rationale claim; ungrounded ones are flagged and excluded from the memo


class ResearchOut(BaseModel):
    """The AI contribution to a Recommendation. The numbers are the engine's; the LLM only proposed and explained."""

    tilt: TiltOut | None
    narrative: NarrativeOut | None


class RecommendationOut(BaseModel):
    id: int
    portfolio_id: str
    version: int
    parent_id: int | None
    root_id: int
    run_id: int
    status: Status
    created_at: str
    created_by: str
    summary: str
    total_value: float
    turnover_pct: float
    trade_lines: list[TradeLineOut]
    suitability: PostTradeSuitability
    post_trade_drift: list[ClassDriftOut]
    approval: ApprovalOut
    research: ResearchOut | None  # null when no approved Insight was in play


class VersionOut(BaseModel):
    id: int
    version: int
    parent_id: int | None
    status: Status
    created_at: str
    created_by: str
    turnover_pct: float
    suitability_status: Rule


class DecisionOut(BaseModel):
    id: int
    recommendation_id: int
    action: Literal["accept", "reject", "modify", "approve_exception", "block", "committee_approve", "committee_reject"]
    rationale: str | None
    actor_name: str
    actor_role: str
    created_at: str
    resulting_status: Status
    resulting_recommendation_id: int | None


class HistoryOut(BaseModel):
    """Every version of the Portfolio's Recommendations, oldest first, and the Decisions taken on them."""

    versions: list[VersionOut] = []
    decisions: list[DecisionOut] = []


class TradeLineIn(BaseModel):
    account_id: str
    symbol: str
    side: Literal["buy", "sell"]
    quantity: int


class DecisionIn(BaseModel):
    action: Literal["accept", "reject", "modify"]
    rationale: str | None = None  # required to reject or modify
    trade_lines: list[TradeLineIn] | None = None  # required to modify: the full replacement set


class DecisionResult(BaseModel):
    decision: DecisionOut
    recommendation: RecommendationOut  # the resulting version: a new one after modify
    new_breaches: list[RuleOut]  # rules in breach on a modified version that were not before


def research_for(db: Session, rec_id: int) -> ResearchOut | None:
    t = db.get(RecommendationTiltRow, rec_id)
    n = db.get(RecommendationNarrativeRow, rec_id)
    if t is None and n is None:
        return None
    claims = grounding.results_for(db, n.check_id) if n and n.check_id else []
    return ResearchOut(
        tilt=TiltOut(
            status=t.status, bound_pp=t.bound_pp, model=t.model, prompt_version=t.prompt_version, error=t.error,
            entries=json.loads(t.entries_json),
        ) if t else None,
        narrative=NarrativeOut(
            status=n.status, model=n.model, prompt_version=n.prompt_version, error=n.error, memo=n.memo,
            claims=[ClaimResultOut(**c.model_dump(), memo_eligible=c.grounded) for c in claims],
        ) if n else None,
    )


def to_out(r: RecommendationRow, cfg: Config, db: Session) -> RecommendationOut:
    p = approvals.plan(r, cfg)
    return RecommendationOut(
        research=research_for(db, r.id),
        id=r.id, portfolio_id=r.client_id, version=r.version, parent_id=r.parent_id, root_id=r.root_id, run_id=r.run_id,
        status=r.status, created_at=r.created_at, created_by=r.created_by, summary=r.summary, total_value=r.total_value,
        turnover_pct=r.turnover_pct, trade_lines=json.loads(r.trade_lines_json),
        suitability=PostTradeSuitability(status=r.suitability_status, rules=json.loads(r.suitability_json)),
        post_trade_drift=json.loads(r.post_trade_drift_json),
        approval=ApprovalOut(
            required_steps=p.required_steps, needs_compliance=p.needs_compliance, high_impact=p.high_impact,
            thresholds=ThresholdsOut(**p.thresholds.model_dump()), reasons=p.reasons,
        ),
    )


def _decision_out(d: DecisionRow) -> DecisionOut:
    return DecisionOut(
        id=d.id, recommendation_id=d.recommendation_id, action=d.action, rationale=d.rationale, actor_name=d.actor_name,
        actor_role=d.actor_role, created_at=d.created_at, resulting_status=d.resulting_status,
        resulting_recommendation_id=d.resulting_recommendation_id,
    )


def history_for(db: Session, client_id: str) -> HistoryOut:
    versions = db.scalars(select(RecommendationRow).where(RecommendationRow.client_id == client_id).order_by(RecommendationRow.id))
    decisions = db.scalars(select(DecisionRow).where(DecisionRow.client_id == client_id).order_by(DecisionRow.id))
    return HistoryOut(
        versions=[VersionOut(
            id=v.id, version=v.version, parent_id=v.parent_id, status=v.status, created_at=v.created_at,
            created_by=v.created_by, turnover_pct=v.turnover_pct, suitability_status=v.suitability_status,
        ) for v in versions],
        decisions=[_decision_out(d) for d in decisions],
    )


@router.get("/recommendations/{recommendation_id}", response_model=RecommendationOut, operation_id="getRecommendation")
def get_recommendation(recommendation_id: int, user: User = Depends(require("recommendation:read")), db: Session = Depends(get_db)):
    r = db.get(RecommendationRow, recommendation_id)
    if r is None:
        raise HTTPException(404, "Recommendation not found")
    return to_out(r, get_config(db), db)


@router.post("/recommendations/{recommendation_id}/decision", response_model=DecisionResult, operation_id="decideRecommendation")
def decide(
    recommendation_id: int,
    body: DecisionIn,
    user: User = Depends(require("recommendation:decide")),
    db: Session = Depends(get_db),
    market: MarketData = Depends(get_market),
):
    cfg = get_config(db)
    lines = [TradeLine(l.account_id, l.symbol, l.side, l.quantity) for l in body.trade_lines] if body.trade_lines is not None else None
    try:
        rec, decision, new_breaches = recommendations.decide(
            db, market, cfg, recommendation_id, body.action, body.rationale, lines,
            audit.Actor.user(user.username, user.role),
        )
    except recommendations.DecisionError as e:
        raise HTTPException(e.status, str(e))
    return DecisionResult(decision=_decision_out(decision), recommendation=to_out(rec, cfg, db), new_breaches=new_breaches)


class ComplianceIn(BaseModel):
    action: Literal["approve", "block"]  # approve the Suitability Exception, or block the Recommendation
    rationale: str | None = None  # required


class CommitteeIn(BaseModel):
    action: Literal["approve", "reject"]
    rationale: str | None = None  # required


class StepResult(BaseModel):
    decision: DecisionOut
    recommendation: RecommendationOut


def _step(db: Session, recommendation_id: int, step: str, action: str, rationale: str | None, user: User) -> StepResult:
    cfg = get_config(db)
    try:
        rec, decision = recommendations.decide_step(
            db, cfg, recommendation_id, step, action, rationale, audit.Actor.user(user.username, user.role),
        )
    except recommendations.DecisionError as e:
        raise HTTPException(e.status, str(e))
    return StepResult(decision=_decision_out(decision), recommendation=to_out(rec, cfg, db))


@router.post("/recommendations/{recommendation_id}/compliance", response_model=StepResult, operation_id="decideCompliance")
def decide_compliance(
    recommendation_id: int, body: ComplianceIn, user: User = Depends(require("compliance:decide")), db: Session = Depends(get_db),
):
    return _step(db, recommendation_id, "compliance", body.action, body.rationale, user)


@router.post("/recommendations/{recommendation_id}/committee", response_model=StepResult, operation_id="decideCommittee")
def decide_committee(
    recommendation_id: int, body: CommitteeIn, user: User = Depends(require("committee:decide")), db: Session = Depends(get_db),
):
    return _step(db, recommendation_id, "committee", body.action, body.rationale, user)
