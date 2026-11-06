"""Drift engine: Asset-Class Drift, Tolerance Band status and Portfolio Drift. Pure, deterministic."""

from dataclasses import dataclass
from typing import Literal

from app.config_service import Band

Status = Literal["ok", "warn", "breach"]


@dataclass(frozen=True)
class ClassDrift:
    asset_class: str
    actual_pct: float
    target_pct: float
    signed_pp: float  # actual - target, in percentage points
    drift_pp: float  # absolute deviation
    status: Status


@dataclass(frozen=True)
class PortfolioDrift:
    classes: list[ClassDrift]
    portfolio_drift_pp: float  # half the sum of absolute Asset-Class Drifts
    max_class_drift_pp: float


def compute_drift(actual: dict[str, float], target: dict[str, float], band: Band) -> PortfolioDrift:
    """Weights are fractions (0-1). An Asset Class absent from `actual` has weight 0."""
    classes = []
    for cls in sorted(set(actual) | set(target)):
        a, t = actual.get(cls, 0.0) * 100, target.get(cls, 0.0) * 100
        d = round(abs(a - t), 9)  # absorb float noise so values exactly on a band edge classify consistently
        status: Status = "breach" if d >= band.breach else "warn" if d >= band.warn else "ok"
        classes.append(ClassDrift(cls, a, t, a - t, d, status))
    return PortfolioDrift(
        classes, sum(c.drift_pp for c in classes) / 2, max((c.drift_pp for c in classes), default=0.0)
    )
