import json
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app import audit
from app.db import AuditEventRow
from app.deps import get_db, require

router = APIRouter(prefix="/api/audit", tags=["audit"])

EventType = Literal[audit.EVENT_TYPES]  # type: ignore[valid-type]


class ActorOut(BaseModel):
    kind: Literal["user", "system"]
    name: str
    role: str | None
    model: str | None
    prompt_version: str | None


class AuditEvent(BaseModel):
    id: int
    type: str
    actor: ActorOut
    timestamp: str
    payload: dict
    parent_ids: list[int]
    portfolio_id: str | None
    client_id: str | None
    recommendation_id: str | None
    report_id: str | None
    previous_hash: str
    hash: str


class AuditPage(BaseModel):
    items: list[AuditEvent]
    total: int


class Verification(BaseModel):
    valid: bool
    checked: int
    first_broken_id: int | None
    reason: str | None
    exchanges_checked: int
    first_broken_exchange_id: int | None  # set when the break is an altered or missing LLM Exchange


def _out(r: AuditEventRow) -> AuditEvent:
    return AuditEvent(
        id=r.id, type=r.type,
        actor=ActorOut(kind=r.actor_kind, name=r.actor_name, role=r.actor_role,
                       model=r.model, prompt_version=r.prompt_version),
        timestamp=r.timestamp, payload=json.loads(r.payload_json), parent_ids=json.loads(r.parent_ids_json),
        portfolio_id=r.portfolio_id, client_id=r.client_id, recommendation_id=r.recommendation_id,
        report_id=r.report_id, previous_hash=r.previous_hash, hash=r.hash,
    )


@router.get("/events", response_model=AuditPage, operation_id="searchAuditEvents",
            dependencies=[Depends(require("audit:read"))])
def search_events(
    type: EventType | None = None,
    actor: str | None = None,
    portfolio_id: str | None = None,
    client_id: str | None = None,
    recommendation_id: str | None = None,
    report_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    rows, total = audit.search(
        db, type=type, actor=actor, portfolio_id=portfolio_id, client_id=client_id,
        recommendation_id=recommendation_id, report_id=report_id,
        date_from=date_from, date_to=date_to, limit=limit, offset=offset,
    )
    return AuditPage(items=[_out(r) for r in rows], total=total)


@router.get("/verify", response_model=Verification, operation_id="verifyAuditChain",
            dependencies=[Depends(require("audit:verify"))])
def verify_chain(db: Session = Depends(get_db)):
    v = audit.verify(db)
    return Verification(valid=v.valid, checked=v.checked, first_broken_id=v.first_broken_id, reason=v.reason,
                        exchanges_checked=v.exchanges_checked, first_broken_exchange_id=v.first_broken_exchange_id)
