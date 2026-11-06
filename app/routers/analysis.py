import json
import time
from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit, grounding, sse
from app.analysis_runs import AnalysisRuns, RunSnapshot
from app.db import AnalysisRunRow, ClientRow, PriorityNarrativeRow, PriorityResultRow, User
from app.deps import get_analysis_runs, get_db, get_llm, get_market, require
from app.market_data import MarketData
from app.rbac import PERMISSIONS

router = APIRouter(prefix="/api", tags=["queue"])

Label = Literal["High", "Medium", "Low"]


class ComponentOut(BaseModel):
    name: Literal["drift", "risk", "opportunity", "urgency"]
    raw: float
    weight: float
    points: float


class ClassDriftOut(BaseModel):
    asset_class: str
    actual_pct: float
    target_pct: float
    signed_pp: float
    drift_pp: float
    status: Literal["ok", "warn", "breach"]


class FindingOut(BaseModel):
    subject: str  # an Instrument, a sector, or a measure such as equity / cash
    actual: float
    limit: float
    status: Literal["pass", "warning", "breach"]
    note: str


class RuleOut(BaseModel):
    rule_id: str
    name: str
    status: Literal["pass", "warning", "breach"]
    message: str
    findings: list[FindingOut]


class QueueNarrative(BaseModel):
    """Why this client, why now. The score is the engine's; `summary` has grounded claims only, flagged ones are in `claims`."""

    status: Literal["complete", "failed"]
    model: str | None
    prompt_version: str | None
    error: str | None
    summary: str | None
    claims: list[grounding.ClaimResult]


class QueueRow(BaseModel):
    portfolio_id: str
    client_id: str
    client_name: str | None  # masked without client:pii
    risk_profile: str
    review_due: str
    days_past_due: int
    sla_breached: bool
    score: float
    label: Label
    components: list[ComponentOut]
    portfolio_drift_pp: float
    asset_class_drift: list[ClassDriftOut]
    total_value: float
    narrative: QueueNarrative | None  # null when the run had no LLM


class Queue(BaseModel):
    run_id: int | None
    as_of: str | None
    items: list[QueueRow]


@router.post(
    "/analysis/runs",
    response_model=RunSnapshot,
    status_code=202,
    operation_id="runAnalysis",
    responses={409: {"model": RunSnapshot, "description": "A run is already in flight: its snapshot"}},
)
def start_run(
    user: User = Depends(require("analysis:run")),
    market: MarketData = Depends(get_market),
    llm=Depends(get_llm),
    runs: AnalysisRuns = Depends(get_analysis_runs),
):
    """Start an Analysis Run in the background (ADR-0005). Only one runs at a time: while one is in flight, `409` with it."""
    snapshot, started = runs.start(market, audit.Actor.user(user.username, user.role), llm)
    if not started:
        return JSONResponse(snapshot.model_dump(), status_code=409)
    return snapshot


@router.get(
    "/analysis/runs/current",
    response_model=RunSnapshot,
    operation_id="getCurrentAnalysisRun",
    responses={204: {"description": "No run in flight"}},
)
def current_run(user: User = Depends(require("analysis:run")), runs: AnalysisRuns = Depends(get_analysis_runs)):
    snapshot = runs.in_flight()
    return snapshot if snapshot is not None else Response(status_code=204)


@router.get("/analysis/runs/{run_id}", response_model=RunSnapshot, operation_id="getAnalysisRun")
def get_run(
    run_id: int,
    user: User = Depends(require("analysis:run")),
    db: Session = Depends(get_db),
    runs: AnalysisRuns = Depends(get_analysis_runs),
):
    """The run's live state while it is in flight, its saved result once it has finished."""
    snapshot = runs.snapshot(db, run_id)
    if snapshot is None:
        raise HTTPException(404, "Analysis Run not found")
    return snapshot


def _progress(snapshot: RunSnapshot, seq: int) -> str:
    return f"id: {seq}\nevent: progress\ndata: {snapshot.model_dump_json()}\n\n"


def _run_events(request: Request, runs: AnalysisRuns, run_id: int, last_seq: int | None) -> Iterator[str]:
    """Server-sent events for one run: its full snapshot on connect and whenever it changes, changes combined at the
    stream poll interval (the Exchange stream's). Ends once the snapshot with the outcome is sent, or after the stream's
    maximum duration, when the browser reconnects with `Last-Event-ID`. An unchanged snapshot is never sent twice."""
    settings = request.app.state.settings
    factory = request.app.state.session_factory
    deadline = time.monotonic() + settings.llm_stream_max_seconds
    last_ping = time.monotonic()
    sent = last_seq
    while time.monotonic() < deadline:
        with factory() as db:
            latest = runs.latest(db, run_id)
        if latest is None:
            return
        snapshot, seq = latest  # seq 0: read from the run row, once the registry no longer holds the run
        if seq != sent:
            sent, last_ping = seq, time.monotonic()
            yield _progress(snapshot, seq)
        elif time.monotonic() - last_ping >= sse.KEEPALIVE_SECONDS:
            last_ping = time.monotonic()
            yield ": keepalive\n\n"
        if snapshot.outcome is not None:
            return
        time.sleep(settings.llm_stream_poll_seconds)


@router.get(
    "/analysis/runs/{run_id}/events",
    operation_id="streamAnalysisRun",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}, 404: {"description": "Analysis Run not found"}},
)
def stream_run(
    run_id: int,
    request: Request,
    user: User = Depends(require("analysis:run")),
    db: Session = Depends(get_db),
    runs: AnalysisRuns = Depends(get_analysis_runs),
    last_event_id: str | None = Header(None),
):
    """Push the run's full snapshot as a `progress` event, id = the run's sequence number, on connect and on every
    change; close after the final snapshot. A reconnect only needs the latest event: `Last-Event-ID` just stops an
    unchanged snapshot being sent again. A value that is not a sequence number is ignored."""
    if runs.latest(db, run_id) is None:
        raise HTTPException(404, "Analysis Run not found")
    db.close()  # hand the auth session's connection back, as the Exchange stream does: a stream polls on its own sessions
    return sse.event_stream(_run_events(request, runs, run_id, sse.last_event_number(last_event_id)))


def _narrative(db: Session, n: PriorityNarrativeRow | None) -> QueueNarrative | None:
    if n is None:
        return None
    return QueueNarrative(
        status=n.status,
        model=n.model,
        prompt_version=n.prompt_version,
        error=n.error,
        summary=n.summary,
        claims=grounding.results_for(db, n.check_id) if n.check_id else [],
    )


_SORTS = {
    "score": PriorityResultRow.score,
    "review_due": PriorityResultRow.review_due,
    "risk_profile": PriorityResultRow.risk_profile,
    "label": PriorityResultRow.score,  # label order == score order
}


@router.get("/queue", response_model=Queue, operation_id="getQueue")
def queue(
    user: User = Depends(require("queue:read")),
    db: Session = Depends(get_db),
    label: Label | None = None,
    risk_profile: str | None = None,
    review_due_from: str | None = Query(None, description="ISO date, inclusive"),
    review_due_to: str | None = Query(None, description="ISO date, inclusive"),
    sla_breached: bool | None = None,
    sort: Literal["score", "review_due", "risk_profile", "label"] = "score",
    order: Literal["asc", "desc"] | None = None,
):
    run = db.scalar(select(AnalysisRunRow).where(AnalysisRunRow.completed).order_by(AnalysisRunRow.id.desc()).limit(1))
    if run is None:
        return Queue(run_id=None, as_of=None, items=[])
    q = (
        select(PriorityResultRow, ClientRow)
        .join(ClientRow, ClientRow.id == PriorityResultRow.client_id)
        .where(PriorityResultRow.run_id == run.id)
    )
    for column, value in (
        (PriorityResultRow.label, label),
        (PriorityResultRow.risk_profile, risk_profile),
        (PriorityResultRow.sla_breached, sla_breached),
    ):
        if value is not None:
            q = q.where(column == value)
    if review_due_from:
        q = q.where(PriorityResultRow.review_due >= review_due_from)
    if review_due_to:
        q = q.where(PriorityResultRow.review_due <= review_due_to)
    desc = (order or ("asc" if sort in ("review_due", "risk_profile") else "desc")) == "desc"
    col = _SORTS[sort]
    q = q.order_by(col.desc() if desc else col.asc(), PriorityResultRow.score.desc(), PriorityResultRow.client_id)
    show_name = "client:pii" in PERMISSIONS[user.role]
    narratives = {
        n.client_id: n for n in db.scalars(select(PriorityNarrativeRow).where(PriorityNarrativeRow.run_id == run.id))
    }
    items = [
        QueueRow(
            portfolio_id=r.client_id,
            client_id=r.client_id,
            client_name=c.name if show_name else None,
            risk_profile=r.risk_profile,
            review_due=r.review_due,
            days_past_due=r.days_past_due,
            sla_breached=r.sla_breached,
            score=r.score,
            label=r.label,
            components=json.loads(r.components_json),
            portfolio_drift_pp=r.portfolio_drift_pp,
            asset_class_drift=json.loads(r.drift_json),
            total_value=r.total_value,
            narrative=_narrative(db, narratives.get(r.client_id)),
        )
        for r, c in db.execute(q)
    ]
    return Queue(run_id=run.id, as_of=run.as_of, items=items)
