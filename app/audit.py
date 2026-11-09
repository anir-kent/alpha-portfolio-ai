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


def exchange_references(row_payload_json: str) -> list[tuple[int, str | None]]:
    """The (id, hash) of every LLM Exchange an event's payload anchors, in Trajectory order (ADR-0010). A legacy event's
    single `exchange_id`/`exchange_hash` is a list of one; a pre-capture event anchors none."""
    payload = json.loads(row_payload_json)
    if "exchanges" in payload:
        return [(ref["exchange_id"], ref.get("exchange_hash")) for ref in payload["exchanges"]]
    if payload.get("exchange_id") is not None:
        return [(payload["exchange_id"], payload.get("exchange_hash"))]
    return []


def _exchange_problem(db: Session, row: AuditEventRow) -> tuple[int, str] | None:
    """Recompute every Exchange an event anchors (ADR-0004 as amended by ADR-0010). None if its Trajectory is intact:
    every Exchange present with the hash the chain pinned, all sharing one Trajectory at positions 0..n-1 in list order,
    and no Exchange of that Trajectory left unanchored. Events with no reference are pre-capture and are not checked; a
    legacy single reference, and a row written before Trajectories, each stand for a Trajectory of one. The event's own
    hash covers the pinned hashes, so a rewritten Exchange whose hash was also recomputed still fails."""
    from app.exchanges import exchange_digest  # local: app.exchanges imports this module

    refs = exchange_references(row.payload_json)
    trajectory_id: str | None = None
    for expected_position, (exchange_id, pinned) in enumerate(refs):
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
        if expected_position == 0:
            trajectory_id = ex.trajectory_id
        # A row written before Trajectories has no id: it is a Trajectory of one, so it must be anchored alone.
        if ex.trajectory_id != trajectory_id or (trajectory_id is None and len(refs) > 1):
            return exchange_id, f"LLM Exchange #{exchange_id} belongs to a different Trajectory from this event's"
        if trajectory_id is None:
            continue
        if ex.trajectory_position != expected_position:
            return (
                exchange_id,
                f"LLM Exchange #{exchange_id} is out of order in this event's Trajectory "
                f"(anchored at position {expected_position}, recorded at {ex.trajectory_position})",
            )
    if trajectory_id is not None:
        unanchored = db.scalars(
            select(LlmExchangeRow.id)
            .where(LlmExchangeRow.trajectory_id == trajectory_id, LlmExchangeRow.id.not_in([i for i, _ in refs]))
            .order_by(LlmExchangeRow.trajectory_position)
        ).first()
        if unanchored is not None:
            return unanchored, f"LLM Exchange #{unanchored} of this event's Trajectory is not anchored by it"
    return None


def verify(db: Session) -> Verification:
    """Walk the chain in order and report the first broken link, or the first event whose anchored Trajectory has an
    altered, missing, reordered or unanchored Exchange."""
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
        exchanges += len(exchange_references(row.payload_json))
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
