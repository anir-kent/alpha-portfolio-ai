from collections.abc import Sequence
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app import extraction, reports
from app.audit import Actor
from app.db import InsightRow, ReportChunkRow, ReportPageRow, ReportRow, User
from app.deps import get_db, get_llm, get_report_index, require
from app.exchanges import ModelLlm
from app.report_index import MAX_BYTES, ReportError, ReportIndex, ReportTooLarge

router = APIRouter(prefix="/api", tags=["research"])

MAX_UPLOAD_BYTES = MAX_BYTES


class InsightOut(BaseModel):
    id: int
    report_id: str
    subject_kind: Literal["sector", "asset_class"]
    subject: str
    direction: Literal["positive", "neutral", "negative"]
    confidence: Literal["low", "medium", "high"]
    page: int
    chunk_id: str | None
    headings: str | None = None  # the cited Chunk's section headings, " > " separated; none for a seeded Insight
    passage: str
    status: Literal["pending", "approved", "rejected"]
    human_verified: bool
    decided_by: str | None
    decided_at: str | None
    decision_note: str | None


class ReportOut(BaseModel):
    id: str
    title: str
    filename: str
    kind: Literal["pdf", "text", "docx", "pptx", "image"]
    uploaded_by: str
    uploaded_at: str
    page_count: int
    human_verified: bool
    extraction_status: Literal["pending", "complete", "failed", "seeded"]
    extraction_error: str | None
    insights: list[InsightOut]


class ReportList(BaseModel):
    items: list[ReportOut]


class InsightList(BaseModel):
    items: list[InsightOut]


class PageOut(BaseModel):
    report_id: str
    page: int
    text: str


class InsightDecision(BaseModel):
    action: Literal["approve", "reject"]
    note: str | None = None


def _insights(db: Session, rows: Sequence[InsightRow]) -> list[InsightOut]:
    """The Insights with the section headings of the Chunks they cite."""
    ids = {i.chunk_id for i in rows if i.chunk_id}
    headings = {
        cid: h
        for cid, h in db.execute(select(ReportChunkRow.id, ReportChunkRow.headings).where(ReportChunkRow.id.in_(ids)))
    }
    return [
        InsightOut.model_validate(i, from_attributes=True).model_copy(
            update={"headings": headings.get(i.chunk_id or "") or None}
        )
        for i in rows
    ]


def _report(db: Session, r: ReportRow) -> ReportOut:
    rows = db.scalars(select(InsightRow).where(InsightRow.report_id == r.id).order_by(InsightRow.id))
    return ReportOut(
        **{f: getattr(r, f) for f in ReportOut.model_fields if f != "insights"},
        insights=_insights(db, list(rows)),
    )


@router.post("/reports", response_model=ReportOut, status_code=201, operation_id="uploadReport")
async def upload_report(
    file: UploadFile,
    request: Request,
    background: BackgroundTasks,
    title: str | None = None,
    user: User = Depends(require("report:upload")),
    db: Session = Depends(get_db),
    llm: ModelLlm = Depends(get_llm),
    index: ReportIndex = Depends(get_report_index),
):
    """Accepts the upload and returns the Report as `pending`; reading, indexing and extraction run in the background."""
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Report file is too large")
    filename = file.filename or "report"
    try:
        # Off the event loop: checking a PDF parses it.
        row, ingested_event_id = await run_in_threadpool(
            extraction.receive,
            db,
            title=title or filename,
            filename=filename,
            content=content,
            uploader=Actor.user(user.username, user.role),
        )
    except ReportTooLarge as e:
        raise HTTPException(413, str(e)) from e
    except ReportError as e:
        raise HTTPException(422, str(e)) from e
    # The request's DB session closes with the response: the job opens its own (FastAPI's documented pattern).
    background.add_task(
        extraction.process,
        request.app.state.session_factory,
        llm,
        index,
        report_id=row.id,
        filename=filename,
        content=content,
        ingested_event_id=ingested_event_id,
    )
    return _report(db, row)


@router.get("/reports", response_model=ReportList, operation_id="listReports")
def list_reports(user: User = Depends(require("report:read")), db: Session = Depends(get_db)):
    return ReportList(
        items=[_report(db, r) for r in db.scalars(select(ReportRow).order_by(ReportRow.uploaded_at, ReportRow.id))]
    )


@router.get("/reports/{report_id}", response_model=ReportOut, operation_id="getReport")
def get_report(report_id: str, user: User = Depends(require("report:read")), db: Session = Depends(get_db)):
    row = db.get(ReportRow, report_id)
    if row is None:
        raise HTTPException(404, "Report not found")
    return _report(db, row)


@router.get("/reports/{report_id}/pages/{page}", response_model=PageOut, operation_id="getReportPage")
def get_page(report_id: str, page: int, user: User = Depends(require("insight:read")), db: Session = Depends(get_db)):
    row = db.get(ReportPageRow, (report_id, page))
    if row is None:
        raise HTTPException(404, "Report page not found")
    return PageOut(report_id=report_id, page=page, text=row.text)


@router.get("/insights", response_model=InsightList, operation_id="listInsights")
def list_insights(
    subject: str | None = Query(None),
    user: User = Depends(require("insight:read")),
    db: Session = Depends(get_db),
):
    """Approved Insights only: the set available for tilt and advisor use."""
    return InsightList(items=_insights(db, reports.approved_insights(db, subject=subject)))


@router.post("/insights/{insight_id}/decision", response_model=InsightOut, operation_id="decideInsight")
def decide_insight(
    insight_id: int,
    body: InsightDecision,
    user: User = Depends(require("insight:approve")),
    db: Session = Depends(get_db),
):
    row = db.get(InsightRow, insight_id)
    if row is None:
        raise HTTPException(404, "Insight not found")
    try:
        reports.decide(db, row, Actor.user(user.username, user.role), body.action, body.note)
    except ReportError as e:
        raise HTTPException(409, str(e)) from e
    return _insights(db, [row])[0]
