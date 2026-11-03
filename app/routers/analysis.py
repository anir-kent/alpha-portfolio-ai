import json
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import audit
from app.analysis import run_analysis
from app.db import AnalysisRunRow, ClientRow, PriorityResultRow, User
from app.deps import get_db, get_market, require
from app.market_data import MarketData
from app.rbac import PERMISSIONS

router = APIRouter(prefix="/api", tags=["queue"])

Label = Literal["High", "Medium", "Low"]


class RunOut(BaseModel):
    run_id: int
    portfolios_scored: int


class ComponentOut(BaseModel):
    name: Literal["drift", "risk", "opportunity", "urgency"]
    raw: float
    weight: float
    points: float


class ClassDriftOut(BaseModel):
    asset_class: str
    actual_pct: float
    target_pct: float
    signed_pp: float
    drift_pp: float
    status: Literal["ok", "warn", "breach"]


class FindingOut(BaseModel):
    subject: str  # an Instrument, a sector, or a measure such as equity / cash
    actual: float
    limit: float
    status: Literal["pass", "warning", "breach"]
    note: str


class RuleOut(BaseModel):
    rule_id: str
    name: str
    status: Literal["pass", "warning", "breach"]
    message: str
    findings: list[FindingOut]


class QueueRow(BaseModel):
    portfolio_id: str
    client_id: str
    client_name: str | None  # masked without client:pii
    risk_profile: str
    review_due: str
    days_past_due: int
    sla_breached: bool
    score: float
    label: Label
    components: list[ComponentOut]
    portfolio_drift_pp: float
    asset_class_drift: list[ClassDriftOut]
    total_value: float


class Queue(BaseModel):
    run_id: int | None
    as_of: str | None
    items: list[QueueRow]


@router.post("/analysis/runs", response_model=RunOut, operation_id="runAnalysis")
def start_run(user: User = Depends(require("analysis:run")), db: Session = Depends(get_db), market: MarketData = Depends(get_market)):
    run_id, n = run_analysis(db, market, audit.Actor.user(user.username, user.role))
    return RunOut(run_id=run_id, portfolios_scored=n)


_SORTS = {
    "score": PriorityResultRow.score, "review_due": PriorityResultRow.review_due,
    "risk_profile": PriorityResultRow.risk_profile, "label": PriorityResultRow.score,  # label order == score order
}


@router.get("/queue", response_model=Queue, operation_id="getQueue")
def queue(
    user: User = Depends(require("queue:read")),
    db: Session = Depends(get_db),
    label: Label | None = None,
    risk_profile: str | None = None,
    review_due_from: str | None = Query(None, description="ISO date, inclusive"),
    review_due_to: str | None = Query(None, description="ISO date, inclusive"),
    sla_breached: bool | None = None,
    sort: Literal["score", "review_due", "risk_profile", "label"] = "score",
    order: Literal["asc", "desc"] | None = None,
):
    run = db.scalar(select(AnalysisRunRow).where(AnalysisRunRow.completed).order_by(AnalysisRunRow.id.desc()).limit(1))
    if run is None:
        return Queue(run_id=None, as_of=None, items=[])
    q = select(PriorityResultRow, ClientRow).join(ClientRow, ClientRow.id == PriorityResultRow.client_id).where(
        PriorityResultRow.run_id == run.id
    )
    for column, value in (
        (PriorityResultRow.label, label), (PriorityResultRow.risk_profile, risk_profile),
        (PriorityResultRow.sla_breached, sla_breached),
    ):
        if value is not None:
            q = q.where(column == value)
    if review_due_from:
        q = q.where(PriorityResultRow.review_due >= review_due_from)
    if review_due_to:
        q = q.where(PriorityResultRow.review_due <= review_due_to)
    desc = (order or ("asc" if sort in ("review_due", "risk_profile") else "desc")) == "desc"
    col = _SORTS[sort]
    q = q.order_by(col.desc() if desc else col.asc(), PriorityResultRow.score.desc(), PriorityResultRow.client_id)
    show_name = "client:pii" in PERMISSIONS[user.role]
    items = [
        QueueRow(
            portfolio_id=r.client_id, client_id=r.client_id, client_name=c.name if show_name else None,
            risk_profile=r.risk_profile, review_due=r.review_due, days_past_due=r.days_past_due,
            sla_breached=r.sla_breached, score=r.score, label=r.label, components=json.loads(r.components_json),
            portfolio_drift_pp=r.portfolio_drift_pp, asset_class_drift=json.loads(r.drift_json), total_value=r.total_value,
        )
        for r, c in db.execute(q)
    ]
    return Queue(run_id=run.id, as_of=run.as_of, items=items)
