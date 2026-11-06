"""Report ingestion and the Insight lifecycle.

A Report is split into pages, the LLM proposes structured Insights, and every Insight starts pending. Only an approved
Insight is retrievable for tilt use (`approved_insights`). An Insight is kept only if its subject is in our taxonomy and
its passage really appears on the cited page; the full grounding validator (ticket 10) builds on `passage_on_page`.
"""
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, ValidationError
from pypdf import PdfReader
from pypdf.errors import PyPdfError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import audit
from app.audit import Actor, format_ts
from app.db import InsightRow, ReportPageRow, ReportRow
from app.llm import LlmClient, LlmError, LlmRequest, exchange_ref
from app.prompts import INSIGHT_EXTRACTION
from app.universe import GICS_SECTORS

ASSET_CLASSES = ("equity", "bond", "cash")
MAX_CHARS = 400_000


class ReportError(Exception):
    """The upload cannot be turned into a Report."""


class ExtractedInsight(BaseModel):
    subject_kind: Literal["sector", "asset_class"]
    subject: str
    direction: Literal["positive", "neutral", "negative"]
    confidence: Literal["low", "medium", "high"]
    page: int
    passage: str


class Extraction(BaseModel):
    insights: list[ExtractedInsight]


EXTRACTION_SCHEMA = Extraction.model_json_schema()


def _now() -> str:
    return format_ts(datetime.now(timezone.utc))


def normalise(text: str) -> str:
    text = text.replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"(?<=\w)-\s+(?=\w)", "-", text)  # PDFs wrap hyphenated words across lines
    return re.sub(r"\s+", " ", text).strip()


def passage_on_page(passage: str, page_text: str) -> bool:
    p = normalise(passage)
    return bool(p) and p in normalise(page_text)


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
            raise ReportError(f"Could not read PDF: {e}")
        kind = "pdf"
    elif name.endswith((".txt", ".md")):
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            raise ReportError("Text Reports must be UTF-8")
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


def extraction_request(pages: list[str]) -> LlmRequest:
    user = "\n\n".join(f"[Page {i}]\n{text.strip()}" for i, text in enumerate(pages, 1))
    return LlmRequest(
        task=INSIGHT_EXTRACTION.name, prompt_version=INSIGHT_EXTRACTION.label,
        system=INSIGHT_EXTRACTION.system, user=user, schema=EXTRACTION_SCHEMA,
    )


def new_report_id() -> str:
    return "RPT-" + uuid.uuid4().hex[:8]


def store_report(
    db: Session, *, report_id: str, title: str, filename: str, kind: str, pages: list[str], uploaded_by: str,
    human_verified: bool, extraction_status: str,
) -> ReportRow:
    row = ReportRow(
        id=report_id, title=title, filename=filename, kind=kind, uploaded_by=uploaded_by, uploaded_at=_now(),
        page_count=len(pages), human_verified=human_verified, extraction_status=extraction_status,
    )
    db.add(row)
    db.add_all(ReportPageRow(report_id=report_id, page=i, text=t) for i, t in enumerate(pages, 1))
    db.commit()
    return row


def add_insight(
    db: Session, report_id: str, e: ExtractedInsight, *, extract_event_id: int, human_verified: bool = False,
) -> InsightRow:
    row = InsightRow(
        report_id=report_id, subject_kind=e.subject_kind, subject=e.subject, direction=e.direction,
        confidence=e.confidence, page=e.page, passage=e.passage, status="pending", human_verified=human_verified,
        created_at=_now(), extract_event_id=extract_event_id,
    )
    db.add(row)
    db.commit()
    return row


def ingest(
    db: Session, llm: LlmClient, *, title: str, filename: str, content: bytes, uploader: Actor,
) -> tuple[ReportRow, list[InsightRow]]:
    """Store the Report, ask the LLM for Insights and keep the cited, in-taxonomy ones as pending."""
    kind, pages = extract_pages(filename, content)
    report_id = new_report_id()
    row = store_report(
        db, report_id=report_id, title=title, filename=filename, kind=kind, pages=pages,
        uploaded_by=uploader.name, human_verified=False, extraction_status="complete",
    )
    ingested = audit.record(
        db, "report_ingested", uploader,
        {"title": title, "filename": filename, "kind": kind, "page_count": len(pages)}, report_id=report_id,
    )
    request = extraction_request(pages)
    try:
        response = llm.complete(request)
        extraction = Extraction.model_validate(response.content)
    except (LlmError, ValidationError) as e:
        row.extraction_status, row.extraction_error = "failed", str(e)[:500]
        db.commit()
        audit.record(
            db, "insight_extracted", Actor.system("insight-extractor", prompt_version=request.prompt_version),
            {"outcome": "failed", "insight_count": 0, "error": str(e)[:500], **exchange_ref(e if isinstance(e, LlmError) else response)},
            parents=[ingested], report_id=report_id,
        )
        return row, []
    kept, dropped = [], []
    for ins in extraction.insights:
        if not valid_subject(ins.subject_kind, ins.subject):
            dropped.append({"subject": ins.subject, "reason": "subject not in taxonomy"})
        elif not 1 <= ins.page <= len(pages):
            dropped.append({"subject": ins.subject, "reason": "cited page does not exist"})
        elif not passage_on_page(ins.passage, pages[ins.page - 1]):
            dropped.append({"subject": ins.subject, "reason": "passage not found on cited page"})
        else:
            kept.append(ins)
    system = Actor.system("insight-extractor", model=response.model, prompt_version=response.prompt_version)
    event = audit.record(
        db, "insight_extracted", system,
        {"outcome": "ok", "insight_count": len(kept), "dropped": dropped,
         **exchange_ref(response)}, parents=[ingested], report_id=report_id,
    )
    return row, [add_insight(db, report_id, ins, extract_event_id=event) for ins in kept]


def decide(db: Session, insight: InsightRow, actor: Actor, action: Literal["approve", "reject"], note: str | None) -> InsightRow:
    if insight.status != "pending":
        raise ReportError(f"Insight is already {insight.status}")
    insight.status = "approved" if action == "approve" else "rejected"
    insight.decided_by, insight.decided_at, insight.decision_note = actor.name, _now(), note
    db.commit()
    audit.record(
        db, "insight_approved" if action == "approve" else "insight_rejected", actor,
        {"insight_id": insight.id, "subject": insight.subject, "direction": insight.direction, "note": note,
         "human_verified": insight.human_verified},
        parents=[insight.extract_event_id], report_id=insight.report_id,
    )
    return insight


def approved_insights(db: Session, *, subject: str | None = None) -> list[InsightRow]:
    """The only retrieval used for tilt: pending and rejected Insights never leave this module."""
    q = select(InsightRow).where(InsightRow.status == "approved").order_by(InsightRow.id)
    if subject:
        q = q.where(InsightRow.subject == subject)
    return list(db.scalars(q))
