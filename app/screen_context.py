"""Screen Context: what the Assistant may see of the screen the user is on (sme-assistant spec, ADR-0006).

The browser sends only a screen identity; the server rebuilds the context from the database through the same service
the screen itself uses, filtered by the user's permissions, so the Assistant never sees more than the screen shows.
Contexts carry Client ids only, never names or emails, even for users holding `client:pii` (ADR-0004). Serialisation is
deterministic: the same screen and data give a byte-identical prompt, which recorded replays depend on.
"""

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import User
from app.market_data import MarketData
from app.rbac import PERMISSIONS


class ScreenIdentity(BaseModel):
    """Which screen the Question was asked on: its kind, the entity ids it shows and an optional selected item."""

    kind: Literal["portfolio"]
    entity_ids: dict[str, str]
    selected_item: str | None = None


@dataclass(frozen=True)
class ScreenContext:
    label: str  # how the drawer names it, e.g. "Portfolio C001"
    portfolio_id: str | None
    text: str  # the serialised context that goes into the prompt

    @property
    def hash(self) -> str:
        return hashlib.sha256(self.text.encode()).hexdigest()


def serialise(value: object) -> str:
    """Stable ordering and formatting, so the same data always gives the same bytes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _portfolio(db: Session, market: MarketData, user: User, screen: ScreenIdentity) -> ScreenContext | None:
    from app.routers.portfolios import portfolio_detail  # local: the router imports the analysis routers

    portfolio_id = screen.entity_ids.get("portfolio_id")
    if not portfolio_id or "portfolio:read" not in PERMISSIONS[user.role]:
        return None
    detail = portfolio_detail(db, market, portfolio_id, user)
    if detail is None:
        return None
    client = detail.client
    drift = detail.drift
    context = {
        "screen": "portfolio",
        "portfolio_id": detail.portfolio_id,
        "client": {  # the Client id stands in for the name; name and email are never included
            "id": client.id,
            "risk_profile": client.risk_profile,
            "objective": client.objective,
            "horizon_years": client.horizon_years,
            "liquidity_needs_pct": client.liquidity_needs_pct,
            "review_due": client.review_due,
        },
        "restrictions": [r.model_dump() for r in detail.restrictions],
        "as_of": detail.as_of,
        "total_value": detail.total_value,
        "holdings": [
            {
                "symbol": h.symbol,
                "name": h.name,
                "asset_class": h.asset_class,
                "account_id": h.account_id,
                "quantity": h.quantity,
                "market_value": h.market_value,
                "weight_pct": h.weight_pct,
            }
            for h in detail.holdings
        ],
        # Target Allocation and Asset-Class Drift come from the latest completed Analysis Run, as on the screen.
        "asset_class_drift": [ac.model_dump() for ac in drift.asset_classes] if drift else None,
        "portfolio_drift_pp": drift.portfolio_drift_pp if drift else None,
        "tolerance_band": drift.tolerance_band.model_dump() if drift else None,
        "latest_analysis_run": (
            {
                "run_id": drift.run_id,
                "as_of": drift.as_of,
                "suitability_status": detail.suitability.status if detail.suitability else None,
                "suitability_rules": [
                    {"rule_id": r.rule_id, "name": r.name, "status": r.status, "message": r.message}
                    for r in detail.suitability.rules
                ]
                if detail.suitability
                else [],
            }
            if drift
            else "No Analysis Run has completed for this Portfolio yet."
        ),
    }
    return ScreenContext(
        label=f"Portfolio {detail.portfolio_id}", portfolio_id=detail.portfolio_id, text=serialise(context)
    )


def build(db: Session, market: MarketData, user: User, screen: ScreenIdentity) -> ScreenContext | None:
    """The Screen Context `user` may see for `screen`, or None when the screen names nothing the user can read (the
    caller refuses without revealing whether it exists)."""
    return _portfolio(db, market, user, screen)
