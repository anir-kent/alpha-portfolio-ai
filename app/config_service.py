import json

from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.db import ConfigRow

PROFILES = ("conservative", "moderate", "growth", "aggressive")


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


class SuitabilityLimits(BaseModel):
    """Limits for the seven Suitability Rules. Percentages are of Portfolio value."""

    max_equity_pct: dict[str, float] = {"conservative": 30, "moderate": 55, "growth": 80, "aggressive": 95}  # SR-01
    single_position_pct: float = Field(default=10, gt=0, le=100)  # SR-02, single names only
    sector_pct: float = Field(default=30, gt=0, le=100)  # SR-03, look-through
    min_cash_pct: dict[str, float] = {"conservative": 5, "moderate": 3, "growth": 2, "aggressive": 1}  # SR-04 floor
    horizon_short_years: int = Field(default=5, ge=0)  # SR-06: a horizon below this is short
    horizon_short_equity_max_pct: float = Field(default=40, ge=0, le=100)  # SR-06
    taxable_gain_pct: float = Field(default=15, gt=0)  # SR-07 warning line, unrealised gains in taxable accounts
    warn_ratio: float = Field(default=0.9, gt=0, lt=1)  # SR-01..03: warning from this share of the limit

    @model_validator(mode="after")
    def _profiles_complete(self):
        for name in ("max_equity_pct", "min_cash_pct"):
            if set(getattr(self, name)) != set(PROFILES):
                raise ValueError(f"{name} must have exactly the Risk Profiles {sorted(PROFILES)}")
        return self


class SuitabilityUpdate(BaseModel):
    """Partial update of SuitabilityLimits: only supplied fields change; per-profile maps merge by profile."""

    max_equity_pct: dict[str, float] | None = None
    single_position_pct: float | None = Field(default=None, gt=0, le=100)
    sector_pct: float | None = Field(default=None, gt=0, le=100)
    min_cash_pct: dict[str, float] | None = None
    horizon_short_years: int | None = Field(default=None, ge=0)
    horizon_short_equity_max_pct: float | None = Field(default=None, ge=0, le=100)
    taxable_gain_pct: float | None = Field(default=None, gt=0)
    warn_ratio: float | None = Field(default=None, gt=0, lt=1)


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
    suitability: SuitabilityLimits = SuitabilityLimits()


class ConfigUpdate(BaseModel):
    """Partial update: only supplied top-level keys change."""

    tolerance_bands: dict[str, Band] | None = None
    priority_weights: PriorityWeights | None = None
    tilt_bound_pp: float | None = Field(default=None, ge=0)
    sla_days: int | None = Field(default=None, gt=0)
    approval_thresholds: ApprovalThresholds | None = None
    suitability: SuitabilityUpdate | None = None


def get_config(db: Session) -> Config:
    stored = {r.key: json.loads(r.value_json) for r in db.query(ConfigRow).all()}
    return Config.model_validate(stored)


def update_config(db: Session, update: ConfigUpdate) -> Config:
    current = get_config(db)
    changes = update.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        if key == "tolerance_bands":  # merge per risk profile
            value = {**{k: b.model_dump() for k, b in current.tolerance_bands.items()}, **value}
        if key == "suitability":  # merge per field, and per profile within the maps
            merged = current.suitability.model_dump()
            for field, v in value.items():
                merged[field] = {**merged[field], **v} if isinstance(v, dict) else v
            value = SuitabilityLimits.model_validate(merged).model_dump()
        row = db.get(ConfigRow, key)
        if row:
            row.value_json = json.dumps(value)
        else:
            db.add(ConfigRow(key=key, value_json=json.dumps(value)))
    db.commit()
    return get_config(db)
