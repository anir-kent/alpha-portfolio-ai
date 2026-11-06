"""Priority scorer: deterministic 0-100 score with a visible breakdown (ADR-0001).

Each component is normalised to 0-100, then weighted (weights from config):
- drift: Portfolio Drift, saturating at DRIFT_FULL_PP points.
- risk: the larger of the worst Asset-Class Drift as a share of the Risk Profile's breach threshold and the
  Suitability Rule points (50 per breach, 15 per warning, capped at 100).
- opportunity: supplied by the caller (0 until Insights exist).
- urgency: days past review-due as a share of the SLA; the SLA is breached once they reach it.
"""

from dataclasses import dataclass
from typing import Literal

from app.config_service import Band, PriorityWeights
from app.drift import PortfolioDrift

DRIFT_FULL_PP = 10.0
HIGH_AT, MEDIUM_AT = 70.0, 40.0

Label = Literal["High", "Medium", "Low"]


@dataclass(frozen=True)
class Component:
    name: str
    raw: float  # 0-100
    weight: float
    points: float  # raw * weight


@dataclass(frozen=True)
class PriorityScore:
    score: float
    label: Label
    components: list[Component]
    days_past_due: int
    sla_breached: bool


def label_for(score: float) -> Label:
    return "High" if score >= HIGH_AT else "Medium" if score >= MEDIUM_AT else "Low"


def _pct(x: float) -> float:
    return max(0.0, min(100.0, x))


def score_portfolio(
    drift: PortfolioDrift,
    band: Band,
    weights: PriorityWeights,
    *,
    days_past_due: int,
    sla_days: int,
    opportunity: float = 0.0,
    suitability_risk: float = 0.0,
) -> PriorityScore:
    raws = {
        "drift": _pct(100 * drift.portfolio_drift_pp / DRIFT_FULL_PP),
        "risk": _pct(max(100 * drift.max_class_drift_pp / band.breach, suitability_risk)),
        "opportunity": _pct(opportunity),
        "urgency": _pct(100 * days_past_due / sla_days),
    }
    components = [Component(n, raws[n], getattr(weights, n), raws[n] * getattr(weights, n)) for n in raws]
    total = sum(c.points for c in components)
    return PriorityScore(total, label_for(total), components, days_past_due, days_past_due >= sla_days)
