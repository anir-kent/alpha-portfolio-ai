"""Global append-only, hash-chained audit trail (ADR-0002).

The only write path is `record`; there is deliberately no update or delete.
Each event's hash covers its content and the previous event's hash, so any
edit, deletion or reordering breaks the chain at a findable row.
"""

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import AuditEventRow
from app.timeutil import as_utc

EVENT_TYPES = (
    "report_ingested",
    "insight_extracted",
    "insight_approved",
    "insight_rejected",
    "analysis_run_started",
    "priority_scored",
    "suitability_evaluated",
    "recommendation_drafted",
    "memo_generated",
    "recommendation_modified",
    "recommendation_superseded",
    "decision_recorded",
    "exception_approved",
    "exception_blocked",
    "access_denied",
)

GENESIS_HASH = "0" * 64
_TS_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_write_lock = threading.Lock()  # chain writes are serialised (ADR-0002)


@dataclass(frozen=True)
class Actor:
    kind: str  # "user" | "system"
    name: str
    role: str | None = None
    model: str | None = None
    prompt_version: str | None = None

    @classmethod
    def user(cls, name: str, role: str) -> "Actor":
        return cls("user", name, role=role)

    @classmethod
    def system(cls, name: str, model: str | None = None, prompt_version: str | None = None) -> "Actor":
        return cls("system", name, model=model, prompt_version=prompt_version)


def format_ts(dt: datetime) -> str:
    return as_utc(dt).astimezone(timezone.utc).strftime(_TS_FORMAT)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(row: AuditEventRow) -> str:
    content = [
        row.type, row.actor_kind, row.actor_name, row.actor_role, row.model, row.prompt_version,
        row.timestamp, json.loads(row.payload_json), json.loads(row.parent_ids_json),
        row.portfolio_id, row.client_id, row.recommendation_id, row.report_id, row.previous_hash,
    ]
    return hashlib.sha256(_canonical(content).encode()).hexdigest()


def record(
    db: Session,
    type: str,
    actor: Actor,
    payload: dict | None = None,
    *,
    parents=(),
    portfolio_id: str | None = None,
    client_id: str | None = None,
    recommendation_id: str | None = None,
    report_id: str | None = None,
) -> int:
    """Append one event to the chain and return its id."""
    if type not in EVENT_TYPES:
        raise ValueError(f"Unknown audit event type: {type}")
    parent_ids = sorted(set(parents))
    with _write_lock:
        if parent_ids:
            found = set(db.scalars(select(AuditEventRow.id).where(AuditEventRow.id.in_(parent_ids))))
            if found != set(parent_ids):
                raise ValueError(f"Unknown parent event ids: {sorted(set(parent_ids) - found)}")
        last = db.scalar(select(AuditEventRow).order_by(AuditEventRow.id.desc()).limit(1))
        row = AuditEventRow(
            type=type, actor_kind=actor.kind, actor_name=actor.name, actor_role=actor.role,
            model=actor.model, prompt_version=actor.prompt_version,
            timestamp=format_ts(datetime.now(timezone.utc)),
            payload_json=_canonical(payload or {}), parent_ids_json=_canonical(parent_ids),
            portfolio_id=portfolio_id, client_id=client_id,
            recommendation_id=recommendation_id, report_id=report_id,
            previous_hash=last.hash if last else GENESIS_HASH, hash="",
        )
        row.hash = _digest(row)
        db.add(row)
        db.commit()
    return row.id


@dataclass(frozen=True)
class Verification:
    valid: bool
    checked: int
    first_broken_id: int | None = None
    reason: str | None = None


def verify(db: Session) -> Verification:
    """Walk the chain in order and report the first broken link."""
    expected_prev = GENESIS_HASH
    checked = 0
    for row in db.scalars(select(AuditEventRow).order_by(AuditEventRow.id)):
        if row.previous_hash != expected_prev:
            return Verification(
                False, checked, row.id,
                "previous hash does not match the preceding event (an earlier event was altered or removed)",
            )
        if _digest(row) != row.hash:
            return Verification(False, checked, row.id, "stored hash does not match event content")
        expected_prev = row.hash
        checked += 1
    return Verification(True, checked)


def search(
    db: Session,
    *,
    type: str | None = None,
    actor: str | None = None,
    portfolio_id: str | None = None,
    client_id: str | None = None,
    recommendation_id: str | None = None,
    report_id: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditEventRow], int]:
    """Newest-first matching events and the total match count."""
    q = select(AuditEventRow)
    for column, value in (
        (AuditEventRow.type, type), (AuditEventRow.actor_name, actor),
        (AuditEventRow.portfolio_id, portfolio_id), (AuditEventRow.client_id, client_id),
        (AuditEventRow.recommendation_id, recommendation_id), (AuditEventRow.report_id, report_id),
    ):
        if value:
            q = q.where(column == value)
    if date_from:
        q = q.where(AuditEventRow.timestamp >= format_ts(date_from))
    if date_to:
        q = q.where(AuditEventRow.timestamp <= format_ts(date_to))
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(AuditEventRow.id.desc()).limit(limit).offset(offset)).all()
    return list(rows), total or 0
