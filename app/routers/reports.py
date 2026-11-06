from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import reports
from app.audit import Actor
from app.db import InsightRow, ReportPageRow, ReportRow, User
from app.deps import get_db, get_llm, require
from app.llm import LlmClient

router = APIRouter(prefix="/api", tags=["research"])

MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class InsightOut(BaseModel):
    id: int
    report_id: str
    subject_kind: Literal["sector", "asset_class"]
    subject: str
    direction: Literal["positive", "neutral", "negative"]
    confidence: Literal["low", "medium", "high"]
    page: int
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
    kind: Literal["pdf", "text"]
    uploaded_by: str
    uploaded_at: str
    page_count: int
    human_verified: bool
    extraction_status: Literal["complete", "failed", "seeded"]
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


def _insight(i: InsightRow) -> InsightOut:
    return InsightOut.model_validate(i, from_attributes=True)


def _report(db: Session, r: ReportRow) -> ReportOut:
    rows = db.scalars(select(InsightRow).where(InsightRow.report_id == r.id).order_by(InsightRow.id))
    return ReportOut(
        **{f: getattr(r, f) for f in ReportOut.model_fields if f != "insights"},
        insights=[_insight(i) for i in rows],
    )


@router.post("/reports", response_model=ReportOut, status_code=201, operation_id="uploadReport")
async def upload_report(
    file: UploadFile,
    title: str | None = None,
    user: User = Depends(require("report:upload")),
    db: Session = Depends(get_db),
    llm: LlmClient = Depends(get_llm),
):
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Report file is too large")
    filename = file.filename or "report"
    try:
        row, _ = reports.ingest(
            db,
            llm,
            title=title or filename,
            filename=filename,
            content=content,
            uploader=Actor.user(user.username, user.role),
        )
    except reports.ReportError as e:
        raise HTTPException(422, str(e)) from e
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
    return InsightList(items=[_insight(i) for i in reports.approved_insights(db, subject=subject)])


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
    except reports.ReportError as e:
        raise HTTPException(409, str(e)) from e
    return _insight(row)
