import json
import os
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.deps import get_db, require
from app.timeutil import as_utc

router = APIRouter(prefix="/api/health", tags=["health"])


class DatabaseHealth(BaseModel):
    status: Literal["ok", "error"]


class MarketDataHealth(BaseModel):
    status: Literal["ok", "missing", "error"]
    snapshot_age_hours: float | None


class LlmHealth(BaseModel):
    status: Literal["ok", "unavailable"]
    mode: str


class Health(BaseModel):
    database: DatabaseHealth
    market_data: MarketDataHealth
    llm: LlmHealth


def _market_data(path: str) -> MarketDataHealth:
    if not os.path.exists(path):
        return MarketDataHealth(status="missing", snapshot_age_hours=None)
    try:
        with open(path) as f:
            as_of = datetime.fromisoformat(json.load(f)["as_of"])
        as_of = as_utc(as_of)
        age = (datetime.now(UTC) - as_of).total_seconds() / 3600
        return MarketDataHealth(status="ok", snapshot_age_hours=round(age, 2))
    except (OSError, ValueError, KeyError, TypeError):
        return MarketDataHealth(status="error", snapshot_age_hours=None)


@router.get("/live", operation_id="getLiveness")
def live() -> dict[str, str]:
    """Unauthenticated liveness probe for process monitors; exposes no system detail."""
    return {"status": "ok"}


@router.get("", response_model=Health, operation_id="getHealth", dependencies=[Depends(require("health:read"))])
def health(request: Request, db: Session = Depends(get_db)):
    s = request.app.state.settings
    try:
        db.execute(text("select 1"))
        database = DatabaseHealth(status="ok")
    except Exception:
        database = DatabaseHealth(status="error")
    llm_ok = s.llm_mode == "recorded" or bool(s.llm_api_key)
    return Health(
        database=database,
        market_data=_market_data(s.market_data_snapshot_path),
        llm=LlmHealth(status="ok" if llm_ok else "unavailable", mode=s.llm_mode),
    )
