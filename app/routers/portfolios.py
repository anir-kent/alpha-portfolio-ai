import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import portfolio_view
from app.config_service import Band
from app.db import AnalysisRunRow, ClientRow, PriorityResultRow, RestrictionRow, User
from app.deps import get_db, get_market, require
from app.market_data import MarketData
from app.rbac import PERMISSIONS
from app.routers.analysis import ClassDriftOut

router = APIRouter(prefix="/api", tags=["portfolios"])


class ClientOut(BaseModel):
    id: str
    name: str | None  # masked without client:pii
    email: str | None  # masked without client:pii
    risk_profile: str
    objective: str
    horizon_years: int
    liquidity_needs_pct: float
    review_due: str


class RestrictionOut(BaseModel):
    kind: str  # instrument | sector
    value: str


class HoldingOut(BaseModel):
    symbol: str
    name: str
    asset_class: str
    kind: str
    account_id: str
    tax_status: str
    quantity: int
    price: float
    market_value: float
    weight_pct: float
    cost_basis_per_unit: float


class SectorExposureOut(BaseModel):
    sector: str
    weight_pct: float
    direct_pct: float
    via_funds_pct: float


class DriftOut(BaseModel):
    run_id: int
    as_of: str
    portfolio_drift_pp: float
    tolerance_band: Band
    asset_classes: list[ClassDriftOut]


class HistoryOut(BaseModel):
    """Recommendation versions and Decisions; empty until the recommendation tickets land."""

    versions: list[dict] = []
    decisions: list[dict] = []


class PortfolioDetail(BaseModel):
    portfolio_id: str
    client: ClientOut
    restrictions: list[RestrictionOut]
    as_of: str
    total_value: float
    holdings: list[HoldingOut]
    drift: DriftOut | None  # null until an analysis run has completed
    sector_exposure: list[SectorExposureOut]
    history: HistoryOut


@router.get("/portfolios/{portfolio_id}", response_model=PortfolioDetail, operation_id="getPortfolio")
def portfolio(
    portfolio_id: str,
    user: User = Depends(require("portfolio:read")),
    db: Session = Depends(get_db),
    market: MarketData = Depends(get_market),
):
    c = db.get(ClientRow, portfolio_id)
    if c is None:
        raise HTTPException(404, "Portfolio not found")
    rows = portfolio_view.holdings(db, market, c.id)
    total = sum(r["market_value"] for r in rows)
    for r in rows:
        r["weight_pct"] = r["market_value"] / total * 100 if total else 0.0

    drift = None
    run = db.scalar(select(AnalysisRunRow).where(AnalysisRunRow.completed).order_by(AnalysisRunRow.id.desc()).limit(1))
    result = db.get(PriorityResultRow, (run.id, c.id)) if run else None
    if run and result:
        cfg = json.loads(run.config_json)
        drift = DriftOut(
            run_id=run.id, as_of=run.as_of, portfolio_drift_pp=result.portfolio_drift_pp,
            tolerance_band=Band(**cfg["tolerance_bands"][c.risk_profile]), asset_classes=json.loads(result.drift_json),
        )
    pii = "client:pii" in PERMISSIONS[user.role]
    restrictions = db.scalars(select(RestrictionRow).where(RestrictionRow.client_id == c.id).order_by(RestrictionRow.id))
    return PortfolioDetail(
        portfolio_id=c.id,
        client=ClientOut(
            id=c.id, name=c.name if pii else None, email=c.email if pii else None, risk_profile=c.risk_profile,
            objective=c.objective, horizon_years=c.horizon_years, liquidity_needs_pct=c.liquidity_needs_pct,
            review_due=c.review_due,
        ),
        restrictions=[RestrictionOut(kind=r.kind, value=r.value) for r in restrictions],
        as_of=market.as_of, total_value=total, holdings=rows, drift=drift,
        sector_exposure=portfolio_view.sector_exposure(rows, market), history=HistoryOut(),
    )
