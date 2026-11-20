"""Insight extraction as a standard RAG pipeline over the Report Index (ADR-0012, amending ADR-0011).

Its own compiled LLM Graph, `extraction`: START → retrieve → generate → END, LangGraph's documented RAG shape. `retrieve`
runs one fixed Retrieval Query per taxonomy subject through the vector store's retriever, filtered to the Report, and
builds the prompt from the de-duplicated union of Chunks. `generate` is the pipeline's own node (`app.llm_graph`): one
structured-output call, so the step is still one LLM Exchange. The run goes through `ModelLlm.run`, which captures it as
every other pipeline step.

The model cites a `chunk_id` and quotes a passage; code checks the subject, the Chunk and the quote, and derives the
page from the Chunk. Retrieval Provenance is collected with LangChain's retriever callbacks and rides on the
`insight_extracted` Audit Event.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict
from uuid import UUID

from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.language_models import BaseChatModel
from langchain_core.vectorstores import VectorStore
from langgraph.config import get_config
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app import audit
from app.audit import Actor
from app.db import ReportChunkRow, ReportPageRow, ReportRow
from app.exchanges import ModelLlm
from app.llm import LlmError, LlmRequest, LlmResponse, exchange_ref
from app.llm_graph import GENERATE, PipelineContext, generate
from app.prompts import INSIGHT_EXTRACTION, RETRIEVAL_QUERIES, RetrievalQuery
from app.report_index import (
    ReportError,
    ReportIndex,
    check_upload,
    chunker_config,
    parse_report,
)
from app.reports import (
    ASSET_CLASSES,
    EXTRACTION_SCHEMA,
    ExtractedInsight,
    Extraction,
    add_insight,
    new_report_id,
    passage_in_chunk,
    passage_on_page,
    store_report,
    valid_subject,
)
from app.universe import GICS_SECTORS

RETRIEVE = "retrieve"


@dataclass(frozen=True)
class SentChunk:
    id: str
    page: int
    headings: str
    text: str


@dataclass(frozen=True)
class ExtractionContext(PipelineContext):
    vector_store: VectorStore
    report_filter: Any  # the backend's own filter for the Report (`report_filter`)
    reranker: BaseDocumentCompressor  # keeps the best Chunks of a query's candidates (Cohere's cross-encoder)
    k: int  # candidates per query, before reranking


class ExtractionState(TypedDict):
    report_id: str
    request: NotRequired[LlmRequest]
    chunks: NotRequired[list[SentChunk]]
    content: NotRequired[dict]


def retrieval_queries() -> list[RetrievalQuery]:
    return RETRIEVAL_QUERIES.for_subjects(GICS_SECTORS, ASSET_CLASSES)


def extraction_request(user: str = "") -> LlmRequest:
    return LlmRequest(
        task=INSIGHT_EXTRACTION.name,
        prompt_version=INSIGHT_EXTRACTION.label,
        system=INSIGHT_EXTRACTION.system,
        user=user,
        schema=EXTRACTION_SCHEMA,
    )


def render_chunks(chunks: list[SentChunk]) -> str:
    return "\n\n".join(f"[Chunk {c.id}] (page {c.page})\n{c.text}" for c in chunks)


class RetrievalProvenance(BaseCallbackHandler):
    """Records every Retrieval Query of a graph run from LangChain's own retriever callbacks: the `candidates` the vector
    store returned and the Chunks the reranker kept (`retrieved`), each in rank order. The vector retriever runs as a
    child of the compression retriever, so its call is told apart by its parent run. A reranker's `relevance_score` is
    kept when a Document carries one."""

    def __init__(self) -> None:
        self._open: dict[UUID, dict[str, Any]] = {}
        self.retrievals: list[dict] = []

    def on_retriever_start(
        self, serialized: dict[str, Any], query: str, *, run_id: UUID, parent_run_id: UUID | None = None, **kwargs: Any
    ) -> None:
        self._open[run_id] = {"query": query, "parent": parent_run_id}

    def on_retriever_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._open.pop(run_id, None)

    def on_retriever_end(self, documents: Sequence[Document], *, run_id: UUID, **kwargs: Any) -> None:
        call = self._open.pop(run_id)
        chunks = []
        for rank, doc in enumerate(documents, 1):
            entry: dict[str, Any] = {"chunk_id": doc.metadata["chunk_id"], "page": doc.metadata["page"], "rank": rank}
            if "relevance_score" in doc.metadata:
                entry["relevance_score"] = doc.metadata["relevance_score"]
            chunks.append(entry)
        parent = self._open.get(call["parent"])
        if parent is not None:  # the base retriever inside the compression retriever: the pre-rerank candidates
            parent["candidates"] = chunks
        else:
            record = {"query": call["query"], "retrieved": chunks}
            if "candidates" in call:
                record["candidates"] = call["candidates"]
            self.retrievals.append(record)


def retrieve(state: ExtractionState, runtime: Runtime[ExtractionContext]) -> dict:
    """The Chunks for the Report's Retrieval Queries, and the extraction request built from them."""
    context = runtime.context
    retriever = ContextualCompressionRetriever(
        base_compressor=context.reranker,
        base_retriever=context.vector_store.as_retriever(
            search_kwargs={"k": context.k, "filter": context.report_filter}
        ),
    )
    found: dict[str, Document] = {}
    try:
        for query in retrieval_queries():
            for doc in retriever.invoke(
                query.text, get_config()
            ):  # the node's config carries the run's callbacks into the retriever
                found.setdefault(doc.metadata["chunk_id"], doc)
    except Exception as e:  # embedding, vector store or rerank: handled like a failed LLM call
        raise LlmError(f"Retrieval failed: {type(e).__name__}: {e}") from e
    if not found:
        raise LlmError("Retrieval found no Chunks for the Report")
    chunks = [SentChunk(id, d.metadata["page"], d.metadata["headings"], d.page_content) for id, d in found.items()]
    return {"request": extraction_request(render_chunks(chunks)), "chunks": chunks}


EXTRACTION = (
    StateGraph(ExtractionState, context_schema=ExtractionContext)
    .add_node(RETRIEVE, retrieve)
    .add_node(GENERATE, generate)  # type: ignore[call-overload]  # reads only `context.model`, which ExtractionContext has
    .add_edge(START, RETRIEVE)
    .add_edge(RETRIEVE, GENERATE)
    .add_edge(GENERATE, END)
    .compile(name="extraction")
)


@dataclass(frozen=True)
class Checked:
    insight: ExtractedInsight
    page: int


def quote_page(passage: str, chunk: SentChunk, pages: list[str]) -> int:
    """The page the passage is on: a Chunk can run across a page break (Docling joins a paragraph that continues onto
    the next page), so the page is the first one, from the Chunk's own page on, whose text holds the passage."""
    return next((n for n in range(chunk.page, len(pages) + 1) if passage_on_page(passage, pages[n - 1])), chunk.page)


def check_insights(extraction: Extraction, sent: list[SentChunk], pages: list[str]) -> tuple[list[Checked], list[dict]]:
    """The Insights that pass the post-checks, and the dropped ones with their reasons: the subject is in the taxonomy,
    the cited Chunk is one that was sent, and the passage is verbatim in it. Code derives the page, never the model."""
    by_id = {c.id: c for c in sent}
    kept, dropped = [], []
    for ins in extraction.insights:
        chunk = by_id.get(ins.chunk_id)
        if not valid_subject(ins.subject_kind, ins.subject):
            dropped.append({"subject": ins.subject, "reason": "subject not in taxonomy"})
        elif chunk is None:
            dropped.append({"subject": ins.subject, "reason": "cited chunk was not among the chunks sent"})
        elif not passage_in_chunk(ins.passage, chunk.text):
            dropped.append({"subject": ins.subject, "reason": "passage not found in cited chunk"})
        else:
            kept.append(Checked(ins, quote_page(ins.passage, chunk, pages)))
    return kept, dropped


def run_extraction(llm: ModelLlm, index: ReportIndex, report_id: str) -> tuple[LlmResponse, list[SentChunk], dict]:
    """(response, Chunks sent, Retrieval Provenance) of one run of the extraction graph on the Report."""
    settings = index.settings
    provenance = RetrievalProvenance()
    try:
        reranker = index.reranker
    except RuntimeError as e:  # no Cohere key
        raise LlmError(str(e)) from e

    def graph(model: BaseChatModel, callbacks: list[BaseCallbackHandler]) -> dict:
        return EXTRACTION.invoke(
            {"report_id": report_id},
            {
                "callbacks": [*callbacks, provenance],
                "metadata": {"llm_task": INSIGHT_EXTRACTION.name, "llm_prompt_version": INSIGHT_EXTRACTION.label},
            },
            context=ExtractionContext(
                model=model,
                vector_store=index.vector_store,
                report_filter=index.report_filter(report_id),
                reranker=reranker,
                k=settings.retrieval_k,
            ),
        )

    state, response = llm.run(extraction_request(), graph, user_from_call=True)
    record = {
        "query_version": RETRIEVAL_QUERIES.label,
        "retrievals": provenance.retrievals,
        "sent_chunk_ids": [c.id for c in state["chunks"]],  # the de-duplicated union the model was actually sent
        "embedding_model": settings.embedding_model,
        "rerank_model": settings.rerank_model,
        "rerank_top_n": settings.rerank_top_n,
        "chunker": chunker_config(settings.embedding_model),
    }
    return response, state["chunks"], record


def receive(db: Session, *, title: str, filename: str, content: bytes, uploader: Actor) -> tuple[ReportRow, int]:
    """Accepts an upload: checks it, stores the Report as pending (its pages and Chunks come with the background job)
    and records `report_ingested`. Returns the Report and that event's id. Raises `ReportError` for a refused upload."""
    kind = check_upload(filename, content)
    row = store_report(
        db,
        report_id=new_report_id(),
        title=title,
        filename=filename,
        kind=kind,
        pages=[],
        uploaded_by=uploader.name,
        human_verified=False,
        extraction_status="pending",
    )
    ingested_event_id = audit.record(
        db,
        "report_ingested",
        uploader,
        {"title": title, "filename": filename, "kind": kind, "size_bytes": len(content)},
        report_id=row.id,
    )
    return row, ingested_event_id


def process(
    session_factory: Callable[[], Session],
    llm: ModelLlm,
    index: ReportIndex,
    *,
    report_id: str,
    filename: str,
    content: bytes,
    ingested_event_id: int,
) -> None:
    """The background job: reads, chunks and indexes the Report, retrieves, asks the LLM for Insights and keeps the
    cited, in-taxonomy ones as pending. It owns its DB session (the request's is closed by then). Whatever goes wrong,
    the Report ends `failed` with the error recorded, never stuck `pending`."""
    with session_factory() as db:
        row = db.get(ReportRow, report_id)
        if row is None:
            return

        def failed(error: Exception, **extra: Any) -> None:
            db.rollback()
            row.extraction_status, row.extraction_error = "failed", str(error)[:500]
            db.commit()
            audit.record(
                db,
                "insight_extracted",
                Actor.system("insight-extractor", prompt_version=INSIGHT_EXTRACTION.label),
                {"outcome": "failed", "insight_count": 0, "error": str(error)[:500], **extra},
                parents=[ingested_event_id],
                report_id=report_id,
            )

        try:
            _process(db, row, llm, index, filename, content, ingested_event_id, failed)
        except Exception as e:  # a bug or an unreadable file must not leave the Report pending
            if row.extraction_status == "pending":  # not already failed by `failed` itself raising on its audit write
                failed(e)


def _process(
    db: Session,
    row: ReportRow,
    llm: ModelLlm,
    index: ReportIndex,
    filename: str,
    content: bytes,
    ingested_event_id: int,
    failed: Callable[..., None],
) -> None:
    report_id = row.id
    try:
        parsed = parse_report(filename, content, report_id=report_id, embedding_model=index.settings.embedding_model)
    except ReportError as e:
        return failed(e)
    row.page_count = len(parsed.pages)
    db.add_all(ReportPageRow(report_id=report_id, page=n, text=t) for n, t in enumerate(parsed.pages, 1))
    db.add_all(
        ReportChunkRow(id=c.id, report_id=report_id, chunk_index=c.index, page=c.page, headings=c.headings, text=c.text)
        for c in parsed.chunks
    )
    db.commit()
    try:
        index.add(report_id, parsed.chunks)
    except Exception as e:  # embedding or vector store
        return failed(LlmError(f"Indexing failed: {type(e).__name__}: {e}"))
    response = None
    try:
        response, sent, provenance = run_extraction(llm, index, report_id)
        extraction = Extraction.model_validate(response.content)
    except (LlmError, ValidationError) as e:
        return failed(e, **exchange_ref(e if isinstance(e, LlmError) else response))
    kept, dropped = check_insights(extraction, sent, parsed.pages)
    system = Actor.system("insight-extractor", model=response.model, prompt_version=response.prompt_version)
    event = audit.record(
        db,
        "insight_extracted",
        system,
        {
            "outcome": "ok",
            "insight_count": len(kept),
            "dropped": dropped,
            "page_count": len(parsed.pages),
            "chunk_count": len(parsed.chunks),
            "retrieval": provenance,
            **exchange_ref(response),
        },
        parents=[ingested_event_id],
        report_id=report_id,
    )
    for c in kept:
        add_insight(db, report_id, c.insight, page=c.page, chunk_id=c.insight.chunk_id, extract_event_id=event)
    row.extraction_status = "complete"
    db.commit()
