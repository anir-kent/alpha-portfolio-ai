"""Report ingestion and the Insight lifecycle.

A Report is chunked and indexed, the LLM proposes structured Insights from the retrieved Chunks (`app.extraction`), and
every Insight starts pending. Only an approved Insight is retrievable for tilt use (`approved_insights`). An Insight is
kept only if its subject is in our taxonomy and its passage really appears in the cited Chunk; the full grounding
validator builds on `passage_on_page`.
"""

import io
import re
import uuid
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.audit import Actor, format_ts
from app.db import InsightRow, ReportPageRow, ReportRow
from app.report_index import ReportError
from app.universe import GICS_SECTORS

ASSET_CLASSES = ("equity", "bond", "cash")
MAX_CHARS = 400_000


class InsightFields(BaseModel):
    subject_kind: Literal["sector", "asset_class"]
    subject: str
    direction: Literal["positive", "neutral", "negative"]
    confidence: Literal["low", "medium", "high"]
    passage: str


class ExtractedInsight(InsightFields):
    """What the model proposes: the Chunk it cites and the quote. Code derives the page from the Chunk."""

    chunk_id: str


class Extraction(BaseModel):
    insights: list[ExtractedInsight]


EXTRACTION_SCHEMA = Extraction.model_json_schema()


def _now() -> str:
    return format_ts(datetime.now(UTC))


def normalise(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "-", text)  # PDFs wrap hyphenated words across lines
    return re.sub(r"\s+", " ", text).strip()


def passage_on_page(passage: str, page_text: str) -> bool:
    p = normalise(passage)
    return bool(p) and p in normalise(page_text)


def passage_in_chunk(passage: str, chunk_text: str) -> bool:
    return passage_on_page(passage, chunk_text)


def valid_subject(kind: str, subject: str) -> bool:
    return subject in (GICS_SECTORS if kind == "sector" else ASSET_CLASSES)


def extract_pages(filename: str, content: bytes) -> tuple[str, list[str]]:
    """(kind, page texts). Text files use form feeds as page breaks; a PDF yields one entry per page."""
    name = filename.lower()
    if name.endswith(".pdf"):
        if not content.startswith(b"%PDF"):
            raise ReportError("File is not a valid PDF")
        try:
            pages = [(p.extract_text() or "") for p in PdfReader(io.BytesIO(content)).pages]
        except (PyPdfError, ValueError, KeyError) as e:
            raise ReportError(f"Could not read PDF: {e}") from e
        kind = "pdf"
    elif name.endswith((".txt", ".md")):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ReportError("Text Reports must be UTF-8") from None
        pages = text.split("\f")
        kind = "text"
    else:
        raise ReportError("Only PDF or text (.txt, .md) Reports are supported")
    while pages and not pages[-1].strip():
        pages.pop()
    if not pages or not any(p.strip() for p in pages):
        raise ReportError("Report contains no extractable text (scanned PDFs are not supported)")
    if sum(len(p) for p in pages) > MAX_CHARS:
        raise ReportError(f"Report is too long (limit {MAX_CHARS} characters)")
    return kind, pages


def new_report_id() -> str:
    return "RPT-" + uuid.uuid4().hex[:8]


def store_report(
    db: Session,
    *,
    report_id: str,
    title: str,
    filename: str,
    kind: str,
    pages: list[str],
    uploaded_by: str,
    human_verified: bool,
    extraction_status: str,
) -> ReportRow:
    row = ReportRow(
        id=report_id,
        title=title,
        filename=filename,
        kind=kind,
        uploaded_by=uploaded_by,
        uploaded_at=_now(),
        page_count=len(pages),
        human_verified=human_verified,
        extraction_status=extraction_status,
    )
    db.add(row)
    db.add_all(ReportPageRow(report_id=report_id, page=i, text=t) for i, t in enumerate(pages, 1))
    db.commit()
    return row


def add_insight(
    db: Session,
    report_id: str,
    e: InsightFields,
    *,
    page: int,
    chunk_id: str | None = None,
    extract_event_id: int,
    human_verified: bool = False,
) -> InsightRow:
    row = InsightRow(
        report_id=report_id,
        subject_kind=e.subject_kind,
        subject=e.subject,
        direction=e.direction,
        confidence=e.confidence,
        page=page,
        chunk_id=chunk_id,
        passage=e.passage,
        status="pending",
        human_verified=human_verified,
        created_at=_now(),
        extract_event_id=extract_event_id,
    )
    db.add(row)
    db.commit()
    return row


def decide(
    db: Session, insight: InsightRow, actor: Actor, action: Literal["approve", "reject"], note: str | None
) -> InsightRow:
    if insight.status != "pending":
        raise ReportError(f"Insight is already {insight.status}")
    insight.status = "approved" if action == "approve" else "rejected"
    insight.decided_by, insight.decided_at, insight.decision_note = actor.name, _now(), note
    db.commit()
    audit.record(
        db,
        "insight_approved" if action == "approve" else "insight_rejected",
        actor,
        {
            "insight_id": insight.id,
            "subject": insight.subject,
            "direction": insight.direction,
            "note": note,
            "human_verified": insight.human_verified,
        },
        parents=[insight.extract_event_id],
        report_id=insight.report_id,
    )
    return insight


def approved_insights(db: Session, *, subject: str | None = None) -> list[InsightRow]:
    """The only retrieval used for tilt: pending and rejected Insights never leave this module."""
    q = select(InsightRow).where(InsightRow.status == "approved").order_by(InsightRow.id)
    if subject:
        q = q.where(InsightRow.subject == subject)
    return list(db.scalars(q))
