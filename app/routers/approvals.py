"""The shared pending-approvals panel: Compliance sees what waits on Compliance, the Investment Committee what waits
on the Committee."""
import json

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import approvals
from app.config_service import get_config
from app.db import ClientRow, RecommendationRow, RestrictionRow, User
from app.deps import get_db, get_market, require
from app.market_data import MarketData
from app.rbac import PERMISSIONS
from app.routers.portfolios import RestrictionOut
from app.routers.recommendations import RecommendationOut, Status, Step, TradeLineOut, to_out

router = APIRouter(prefix="/api", tags=["approvals"])

_STEP_FOR_PERMISSION = {"compliance:decide": "compliance", "committee:decide": "committee"}


class FlaggedFinding(BaseModel):
    subject: str  # an Instrument, a sector, or a measure such as equity / cash
    actual: float
    limit: float
    status: str
    note: str
    affected_trade_lines: list[TradeLineOut]


class FlaggedRuleOut(BaseModel):
    rule_id: str
    name: str
    status: str
    message: str
    findings: list[FlaggedFinding]


class ApprovalItem(BaseModel):
    step: Step
    status: Status
    portfolio_id: str
    client_name: str | None  # masked without client:pii
    risk_profile: str
    recommendation: RecommendationOut
    rules: list[FlaggedRuleOut]
    restrictions: list[RestrictionOut]


class ApprovalsOut(BaseModel):
    items: list[ApprovalItem]



def _flagged(rec: RecommendationRow, market: MarketData) -> list[FlaggedRuleOut]:
    lines = json.loads(rec.trade_lines_json)
    out = []
    for r in json.loads(rec.suitability_json):
        if r["status"] == "pass":
            continue
        findings = [
            FlaggedFinding(**f, affected_trade_lines=approvals.affected_lines(f["subject"], lines, market))
            for f in r["findings"] if f["status"] != "pass"
        ]
        out.append(FlaggedRuleOut(rule_id=r["rule_id"], name=r["name"], status=r["status"], message=r["message"], findings=findings))
    return out


@router.get("/approvals", response_model=ApprovalsOut, operation_id="listApprovals")
def pending_approvals(
    user: User = Depends(require("approvals:read")), db: Session = Depends(get_db), market: MarketData = Depends(get_market),
):
    perms = PERMISSIONS[user.role]
    steps = [s for p, s in _STEP_FOR_PERMISSION.items() if p in perms]
    cfg = get_config(db)
    pii = "client:pii" in perms
    recs = db.scalars(
        select(RecommendationRow).where(RecommendationRow.status.in_([approvals.PENDING_FOR[s] for s in steps]))
        .order_by(RecommendationRow.id)
    )
    items = []
    for rec in recs:
        c = db.get(ClientRow, rec.client_id)
        restrictions = db.scalars(select(RestrictionRow).where(RestrictionRow.client_id == c.id).order_by(RestrictionRow.id))
        items.append(ApprovalItem(
            step=approvals.STEP_OF[rec.status], status=rec.status, portfolio_id=c.id, client_name=c.name if pii else None,
            risk_profile=c.risk_profile, recommendation=to_out(rec, cfg), rules=_flagged(rec, market),
            restrictions=[RestrictionOut(kind=r.kind, value=r.value) for r in restrictions],
        ))
    return ApprovalsOut(items=items)
