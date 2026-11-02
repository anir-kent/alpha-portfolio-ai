import json

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db import ConfigRow


class Band(BaseModel):
    warn: float = Field(gt=0)
    breach: float = Field(gt=0)

    @model_validator(mode="after")
    def _ordered(self):
        if self.warn >= self.breach:
            raise ValueError("warn must be below breach")
        return self


class PriorityWeights(BaseModel):
    drift: float = Field(ge=0)
    risk: float = Field(ge=0)
    opportunity: float = Field(ge=0)
    urgency: float = Field(ge=0)

    @model_validator(mode="after")
    def _sum_to_one(self):
        if abs(self.drift + self.risk + self.opportunity + self.urgency - 1.0) > 1e-6:
            raise ValueError("priority weights must sum to 1")
        return self


class ApprovalThresholds(BaseModel):
    turnover_pct: float = Field(gt=0, le=100)
    trade_line_pct: float = Field(gt=0, le=100)


class Config(BaseModel):
    """Single configuration surface read by later engines."""

    tolerance_bands: dict[str, Band] = {
        "conservative": Band(warn=2, breach=4),
        "moderate": Band(warn=3, breach=5),
        "growth": Band(warn=4, breach=6),
        "aggressive": Band(warn=5, breach=8),
    }
    priority_weights: PriorityWeights = PriorityWeights(drift=0.4, risk=0.3, opportunity=0.2, urgency=0.1)
    tilt_bound_pp: float = Field(default=2.0, ge=0)
    sla_days: int = Field(default=30, gt=0)
    approval_thresholds: ApprovalThresholds = ApprovalThresholds(turnover_pct=15.0, trade_line_pct=10.0)


class ConfigUpdate(BaseModel):
    """Partial update: only supplied top-level keys change."""

    tolerance_bands: dict[str, Band] | None = None
    priority_weights: PriorityWeights | None = None
    tilt_bound_pp: float | None = Field(default=None, ge=0)
    sla_days: int | None = Field(default=None, gt=0)
    approval_thresholds: ApprovalThresholds | None = None


def get_config(db: Session) -> Config:
    stored = {r.key: json.loads(r.value_json) for r in db.query(ConfigRow).all()}
    return Config.model_validate(stored)


def update_config(db: Session, update: ConfigUpdate) -> Config:
    current = get_config(db)
    changes = update.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        if key == "tolerance_bands":  # merge per risk profile
            value = {**{k: b.model_dump() for k, b in current.tolerance_bands.items()}, **value}
        row = db.get(ConfigRow, key)
        if row:
            row.value_json = json.dumps(value)
        else:
            db.add(ConfigRow(key=key, value_json=json.dumps(value)))
    db.commit()
    return get_config(db)
