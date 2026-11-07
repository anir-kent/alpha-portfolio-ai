"""Global append-only, hash-chained audit trail (ADR-0002).

The only write path is `record`; there is deliberately no update or delete.
Each event's hash covers its content and the previous event's hash, so any
edit, deletion or reordering breaks the chain at a findable row.
"""

import hashlib
import json
import threading
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.db import AuditEventRow, LlmExchangeRow
from app.timeutil import as_utc

EVENT_TYPES = (
    "report_ingested",
    "insight_extracted",
    "insight_approved",
    "insight_rejected",
    "analysis_run_started",
    "priority_scored",
    "suitability_evaluated",
    "research_tilt_proposed",
    "research_tilt_applied",
    "recommendation_drafted",
    "memo_generated",
    "priority_narrative_generated",
    "grounding_checked",
    "claim_ungrounded",
    "adversarial_fixtures_run",
    "recommendation_modified",
    "recommendation_superseded",
    "decision_recorded",
    "exception_approved",
    "exception_blocked",
    "access_denied",
    "assistant.answered",
    "assistant.refused",
    "assistant.failed",
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
    return as_utc(dt).astimezone(UTC).strftime(_TS_FORMAT)


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _digest(row: AuditEventRow) -> str:
    content = [
        row.type,
        row.actor_kind,
        row.actor_name,
        row.actor_role,
        row.model,
        row.prompt_version,
        row.timestamp,
        json.loads(row.payload_json),
        json.loads(row.parent_ids_json),
        row.portfolio_id,
        row.client_id,
        row.recommendation_id,
        row.report_id,
        row.previous_hash,
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
            type=type,
            actor_kind=actor.kind,
            actor_name=actor.name,
            actor_role=actor.role,
            model=actor.model,
            prompt_version=actor.prompt_version,
            timestamp=format_ts(datetime.now(UTC)),
            payload_json=_canonical(payload or {}),
            parent_ids_json=_canonical(parent_ids),
            portfolio_id=portfolio_id,
            client_id=client_id,
            recommendation_id=recommendation_id,
            report_id=report_id,
            previous_hash=last.hash if last else GENESIS_HASH,
            hash="",
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
    exchanges_checked: int = 0
    first_broken_exchange_id: int | None = None


def exchange_reference(row_payload_json: str) -> tuple[int | None, str | None]:
    """The (id, hash) of the LLM Exchange an event's payload references; (None, None) for a pre-capture event."""
    payload = json.loads(row_payload_json)
    return payload.get("exchange_id"), payload.get("exchange_hash")


def _exchange_problem(db: Session, row: AuditEventRow) -> tuple[int, str] | None:
    """Recompute the Exchange an event references (ADR-0004). None if it is intact; events with no reference are
    pre-capture and are not checked. The event's own hash covers the referenced hash, so a rewritten Exchange whose
    hash was also recomputed still fails against the hash the chain pinned."""
    from app.exchanges import exchange_digest  # local: app.exchanges imports this module

    exchange_id, pinned = exchange_reference(row.payload_json)
    if exchange_id is None:
        return None
    try:
        ex = db.get(LlmExchangeRow, exchange_id)
    except OperationalError:  # the whole store is gone, which is the same finding as a missing row
        ex = None
    if ex is None:
        return exchange_id, f"LLM Exchange #{exchange_id} referenced by this event is missing"
    if exchange_digest(ex) != pinned or ex.hash != pinned:
        return (
            exchange_id,
            f"LLM Exchange #{exchange_id} referenced by this event was altered (its hash no longer matches)",
        )
    return None


def verify(db: Session) -> Verification:
    """Walk the chain in order and report the first broken link, or the first event whose referenced Exchange is
    altered or missing."""
    expected_prev = GENESIS_HASH
    checked = 0
    exchanges = 0
    for row in db.scalars(select(AuditEventRow).order_by(AuditEventRow.id)):
        if row.previous_hash != expected_prev:
            return Verification(
                False,
                checked,
                row.id,
                "previous hash does not match the preceding event (an earlier event was altered or removed)",
                exchanges_checked=exchanges,
            )
        if _digest(row) != row.hash:
            return Verification(
                False, checked, row.id, "stored hash does not match event content", exchanges_checked=exchanges
            )
        problem = _exchange_problem(db, row)
        if problem:
            return Verification(
                False, checked, row.id, problem[1], exchanges_checked=exchanges, first_broken_exchange_id=problem[0]
            )
        if exchange_reference(row.payload_json)[0] is not None:
            exchanges += 1
        expected_prev = row.hash
        checked += 1
    return Verification(True, checked, exchanges_checked=exchanges)


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
    event_id: int | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[AuditEventRow], int]:
    """Newest-first matching events and the total match count. `event_id` narrows the search to one event, to check
    whether it is among the matches."""
    q = select(AuditEventRow)
    if event_id is not None:
        q = q.where(AuditEventRow.id == event_id)
    for column, value in (
        (AuditEventRow.type, type),
        (AuditEventRow.actor_name, actor),
        (AuditEventRow.portfolio_id, portfolio_id),
        (AuditEventRow.client_id, client_id),
        (AuditEventRow.recommendation_id, recommendation_id),
        (AuditEventRow.report_id, report_id),
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
