import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, recommendations
from app.config_service import get_config
from app.db import DecisionRow, RecommendationRow, User
from app.deps import get_db, get_market, require
from app.market_data import MarketData
from app.rebalance import TradeLine
from app.routers.analysis import ClassDriftOut, RuleOut

router = APIRouter(prefix="/api", tags=["recommendations"])

Status = Literal["pending_advisor", "pending_compliance", "approved", "rejected", "superseded"]
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
    action: Literal["accept", "reject", "modify"]
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


def to_out(r: RecommendationRow) -> RecommendationOut:
    return RecommendationOut(
        id=r.id, portfolio_id=r.client_id, version=r.version, parent_id=r.parent_id, root_id=r.root_id, run_id=r.run_id,
        status=r.status, created_at=r.created_at, created_by=r.created_by, summary=r.summary, total_value=r.total_value,
        turnover_pct=r.turnover_pct, trade_lines=json.loads(r.trade_lines_json),
        suitability=PostTradeSuitability(status=r.suitability_status, rules=json.loads(r.suitability_json)),
        post_trade_drift=json.loads(r.post_trade_drift_json),
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
    return to_out(r)


@router.post("/recommendations/{recommendation_id}/decision", response_model=DecisionResult, operation_id="decideRecommendation")
def decide(
    recommendation_id: int,
    body: DecisionIn,
    user: User = Depends(require("recommendation:decide")),
    db: Session = Depends(get_db),
    market: MarketData = Depends(get_market),
):
    lines = [TradeLine(l.account_id, l.symbol, l.side, l.quantity) for l in body.trade_lines] if body.trade_lines is not None else None
    try:
        rec, decision, new_breaches = recommendations.decide(
            db, market, get_config(db), recommendation_id, body.action, body.rationale, lines,
            audit.Actor.user(user.username, user.role),
        )
    except recommendations.DecisionError as e:
        raise HTTPException(e.status, str(e))
    return DecisionResult(decision=_decision_out(decision), recommendation=to_out(rec), new_breaches=new_breaches)
