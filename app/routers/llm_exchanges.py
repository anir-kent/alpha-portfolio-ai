import json
import time
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import ColumnElement, Select, String, cast, func, select
from sqlalchemy.orm import Session

from app import audit, grounding
from app.audit import format_ts
from app.db import AuditEventRow, LlmExchangeRow
from app.deps import get_db, require
from app.routers.audit import AuditEvent, event_out
from app.sse import KEEPALIVE_SECONDS, event_stream, last_event_number

router = APIRouter(prefix="/api/llm", tags=["llm"])


class ExchangeOut(BaseModel):
    id: int
    created_at: str
    task: str
    prompt_version: str
    model: str | None
    mode: Literal["live", "recorded"]
    endpoint_host: str | None
    system_text: str
    user_prompt: str
    reply_schema: dict
    messages: list[dict] | None
    raw_reply: str | None
    parsed_content: dict | None
    usage: dict | None
    latency_ms: int | None
    # "measured" for a live call; a replay has no real tokens or latency, so they are absent, not zero.
    telemetry: Literal["measured", "not_available_replayed"]
    outcome: Literal["ok", "error"]
    error: str | None
    # The LLM Trajectory this request belongs to and its 0-based place in it (ADR-0010). A row written before
    # Trajectories existed has neither and is a Trajectory of one.
    trajectory_id: str | None
    trajectory_position: int | None
    hash: str


class GroundingSummary(BaseModel):
    total: int
    grounded: int
    ungrounded: int


class GroundingVerdict(BaseModel):
    """The validator's verdict on the Claims one referencing event produced, joined through that event's check id."""

    check_id: str
    summary: GroundingSummary
    claims: list[grounding.ClaimResult]  # ungrounded ones included, flagged


class ExchangeDetail(ExchangeOut):
    used_by: list[AuditEvent]  # the Audit Events whose payload references this Exchange
    grounding: list[GroundingVerdict]
    # Every Exchange of this one's Trajectory, in position order: the drawer's "step k of n" and its neighbours.
    trajectory_exchange_ids: list[int]


def _loads(text: str | None):
    return None if text is None else json.loads(text)


def exchange_out(r: LlmExchangeRow) -> ExchangeOut:
    return ExchangeOut(
        id=r.id,
        created_at=r.created_at,
        task=r.task,
        prompt_version=r.prompt_version,
        model=r.model,
        mode=r.mode,
        endpoint_host=r.endpoint_host,
        system_text=r.system_text,
        user_prompt=r.user_prompt,
        reply_schema=json.loads(r.reply_schema_json),
        messages=_loads(r.messages_json),
        raw_reply=r.raw_reply,
        parsed_content=_loads(r.parsed_content_json),
        usage=_loads(r.usage_json),
        latency_ms=r.latency_ms,
        telemetry="measured" if r.mode == "live" else "not_available_replayed",
        outcome=r.outcome,
        error=r.error,
        trajectory_id=r.trajectory_id,
        trajectory_position=r.trajectory_position,
        hash=r.hash,
    )


class ExchangeSummary(BaseModel):
    """One feed row: everything needed to scan, none of the bulk text."""

    id: int
    created_at: str
    task: str
    prompt_version: str
    model: str | None
    mode: Literal["live", "recorded"]
    outcome: Literal["ok", "error"]
    latency_ms: int | None
    usage: dict | None
    telemetry: Literal["measured", "not_available_replayed"]
    error: str | None  # a failed call's message, cut short: a summary for the row, the full text is in the detail
    trajectory_id: str | None  # None for a row written before Trajectories, which is a Trajectory of one
    trajectory_position: int | None
    trajectory_length: int  # Exchanges in its Trajectory, whether or not the current filters match them all
    hash: str
    recommendation_id: str | None  # from the Audit Event that references this Exchange
    portfolio_id: str | None


class ExchangePage(BaseModel):
    items: list[ExchangeSummary]
    total: int


def referencing_events(db: Session, exchange_ids: list[int]) -> dict[int, list[AuditEventRow]]:
    """The Audit Events whose payload points at each Exchange, oldest first."""
    found: dict[int, list[AuditEventRow]] = {}
    if not exchange_ids:
        return found
    wanted = set(exchange_ids)
    for ev in db.scalars(
        select(AuditEventRow).where(AuditEventRow.payload_json.contains('"exchange_id"')).order_by(AuditEventRow.id)
    ):
        for exchange_id, _ in audit.exchange_references(ev.payload_json):
            if exchange_id in wanted:
                found.setdefault(exchange_id, []).append(ev)
    return found


ERROR_SUMMARY_CHARS = 200


# A row written before Trajectories has no `trajectory_id` and is a Trajectory of one, keyed by its own id. The SQL
# expression and the Python function give the same key.
def trajectory_key_sql() -> ColumnElement[str]:
    return func.coalesce(LlmExchangeRow.trajectory_id, "exchange-" + cast(LlmExchangeRow.id, String))


def trajectory_key(r: LlmExchangeRow) -> str:
    return r.trajectory_id or f"exchange-{r.id}"


def trajectory_lengths(db: Session, rows: list[LlmExchangeRow]) -> dict[str, int]:
    """How many Exchanges each row's Trajectory holds, by Trajectory key, whatever filters selected the rows."""
    ids = {r.trajectory_id for r in rows if r.trajectory_id is not None}
    counts: Iterable[tuple[str | None, int]] = (
        db.execute(
            select(LlmExchangeRow.trajectory_id, func.count())
            .where(LlmExchangeRow.trajectory_id.in_(ids))
            .group_by(LlmExchangeRow.trajectory_id)
        ).tuples()
        if ids
        else []
    )
    found = {trajectory_id: n for trajectory_id, n in counts if trajectory_id is not None}
    return {trajectory_key(r): found.get(r.trajectory_id or "", 1) for r in rows}


def summaries(db: Session, rows: list[LlmExchangeRow]) -> list[ExchangeSummary]:
    """Feed rows for `rows`, in the given order, each with its linked scope and its Trajectory's length."""
    events = referencing_events(db, [r.id for r in rows])
    lengths = trajectory_lengths(db, rows)
    return [exchange_summary(r, events.get(r.id, []), lengths[trajectory_key(r)]) for r in rows]


def exchange_summary(r: LlmExchangeRow, events: list[AuditEventRow], length: int) -> ExchangeSummary:
    return ExchangeSummary(
        error=None if r.error is None else r.error[:ERROR_SUMMARY_CHARS],
        id=r.id,
        created_at=r.created_at,
        task=r.task,
        prompt_version=r.prompt_version,
        model=r.model,
        mode=r.mode,
        outcome=r.outcome,
        latency_ms=r.latency_ms,
        usage=_loads(r.usage_json),
        trajectory_id=r.trajectory_id,
        trajectory_position=r.trajectory_position,
        trajectory_length=length,
        hash=r.hash,
        telemetry="measured" if r.mode == "live" else "not_available_replayed",
        recommendation_id=next((e.recommendation_id for e in events if e.recommendation_id), None),
        portfolio_id=next((e.portfolio_id for e in events if e.portfolio_id), None),
    )


@router.get(
    "/exchanges",
    response_model=ExchangePage,
    operation_id="listLlmExchanges",
    dependencies=[Depends(require("llm:read"))],
)
def list_exchanges(
    task: str | None = None,
    prompt_version: str | None = None,
    mode: Literal["live", "recorded"] | None = None,
    outcome: Literal["ok", "error"] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    trajectory_id: str | None = None,
    group: Literal["trajectory"] | None = Query(
        None,
        description="`trajectory`: page by LLM Trajectory, newest first, so `total`, `limit` and `offset` count "
        "Trajectories and each one's matching Exchanges come together in position order.",
    ),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    q = select(LlmExchangeRow)
    for column, value in (
        (LlmExchangeRow.task, task),
        (LlmExchangeRow.prompt_version, prompt_version),
        (LlmExchangeRow.mode, mode),
        (LlmExchangeRow.outcome, outcome),
        (LlmExchangeRow.trajectory_id, trajectory_id),
    ):
        if value:
            q = q.where(column == value)
    if date_from:
        q = q.where(LlmExchangeRow.created_at >= format_ts(date_from))
    if date_to:
        q = q.where(LlmExchangeRow.created_at <= format_ts(date_to))
    if group == "trajectory":
        total, rows = _page_by_trajectory(db, q, limit, offset)
    else:
        total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
        rows = list(db.scalars(q.order_by(LlmExchangeRow.id.desc()).limit(limit).offset(offset)))
    return ExchangePage(items=summaries(db, rows), total=total)


def _page_by_trajectory(db: Session, q: Select, limit: int, offset: int) -> tuple[int, list[LlmExchangeRow]]:
    """The number of Trajectories with an Exchange matching `q`, and a page of them, newest first: each one's matching
    Exchanges together, in position order."""
    key = trajectory_key_sql()
    groups = q.with_only_columns(key).group_by(key)
    total = db.scalar(select(func.count()).select_from(groups.subquery())) or 0
    page = list(db.scalars(groups.order_by(func.max(LlmExchangeRow.id).desc()).limit(limit).offset(offset)))
    order = {k: i for i, k in enumerate(page)}
    matching = db.scalars(q.where(key.in_(page))).all() if page else []
    return total, sorted(matching, key=lambda r: (order[trajectory_key(r)], r.trajectory_position or 0))


STREAM_BATCH = 100
LINK_GRACE_SECONDS = 2.0  # an Exchange is stored just before the Audit Event that references it; wait this long for it


def _sse(summary: ExchangeSummary) -> str:
    return f"id: {summary.id}\nevent: exchange\ndata: {summary.model_dump_json()}\n\n"


def _awaiting_link(row: LlmExchangeRow, events: dict[int, list[AuditEventRow]]) -> bool:
    """A fresh Exchange whose event is not written yet: streaming it now would show it with no linked Recommendation."""
    age = (
        datetime.now(UTC) - datetime.strptime(row.created_at, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)
    ).total_seconds()
    return row.id not in events and age < LINK_GRACE_SECONDS


def _exchange_events(request: Request, after_id: int | None) -> Iterator[str]:
    """Server-sent events for Exchanges newer than `after_id` (the tail when None), in id order, by polling the store.
    No in-process publisher, so any worker can serve any client. Exchange ids are assigned and committed in order
    (SQLite has one writer), so an id cursor neither skips nor repeats a row."""
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    deadline = time.monotonic() + settings.llm_stream_max_seconds
    last_ping = time.monotonic()
    cursor = after_id
    if cursor is None:
        with factory() as db:
            cursor = db.scalar(select(func.max(LlmExchangeRow.id))) or 0
    yield f"id: {cursor}\n\n"  # an id-only block: even a client that sees no Exchange resumes from here
    while time.monotonic() < deadline:
        with factory() as db:
            rows = db.scalars(
                select(LlmExchangeRow).where(LlmExchangeRow.id > cursor).order_by(LlmExchangeRow.id).limit(STREAM_BATCH)
            ).all()
            events = referencing_events(db, [r.id for r in rows])
            ready = []
            for r in rows:  # in id order; the first one still waiting for its event holds back those after it
                if _awaiting_link(r, events):
                    break
                ready.append(r)
            chunks = [_sse(summary) for summary in summaries(db, ready)]
            rows = ready
        if rows:
            cursor = rows[-1].id
            last_ping = time.monotonic()
            yield from chunks
            if len(rows) == STREAM_BATCH:
                continue  # more waiting: drain before sleeping
        elif time.monotonic() - last_ping >= KEEPALIVE_SECONDS:
            last_ping = time.monotonic()
            yield ": keepalive\n\n"
        time.sleep(settings.llm_stream_poll_seconds)


@router.get(
    "/exchanges/stream",
    operation_id="streamLlmExchanges",
    dependencies=[Depends(require("llm:read"))],
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def stream_exchanges(request: Request, last_event_id: str | None = Header(None), db: Session = Depends(get_db)):
    """Push each new Exchange (as a summary row) once, in id order. A reconnect sends the standard `Last-Event-ID`;
    a value that is not an id is ignored and the stream starts at the tail."""
    db.close()  # hand the auth session's connection back: a stream lives for minutes and polls on its own sessions
    return event_stream(_exchange_events(request, last_event_number(last_event_id)))


@router.get(
    "/exchanges/{exchange_id}",
    response_model=ExchangeDetail,
    operation_id="getLlmExchange",
    dependencies=[Depends(require("llm:read"))],
)
def get_exchange(exchange_id: int, db: Session = Depends(get_db)):
    detail = exchange_detail(db, exchange_id)
    if detail is None:
        raise HTTPException(404, "LLM exchange not found")
    return detail


def exchange_detail(db: Session, exchange_id: int) -> ExchangeDetail | None:
    """One Exchange with the Audit Events that used it and their grounding verdicts. Shared with the Assistant's
    Exchanges Screen Context."""
    row = db.get(LlmExchangeRow, exchange_id)
    if row is None:
        return None
    events = referencing_events(db, [row.id]).get(row.id, [])
    verdicts = []
    for check_id in dict.fromkeys(c for e in events if (c := json.loads(e.payload_json).get("check_id"))):
        claims = grounding.results_for(db, check_id)
        verdicts.append(
            GroundingVerdict(check_id=check_id, summary=GroundingSummary(**grounding.summarise(claims)), claims=claims)
        )
    steps = (
        list(
            db.scalars(
                select(LlmExchangeRow.id)
                .where(LlmExchangeRow.trajectory_id == row.trajectory_id)
                .order_by(LlmExchangeRow.trajectory_position, LlmExchangeRow.id)
            )
        )
        if row.trajectory_id is not None
        else [row.id]
    )
    return ExchangeDetail(
        **exchange_out(row).model_dump(),
        used_by=[event_out(e) for e in events],
        grounding=verdicts,
        trajectory_exchange_ids=steps,
    )
