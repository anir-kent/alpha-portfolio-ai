"""Seam: Insight extraction as RAG over the Report Index (ADR-0012). An upload is converted by Docling and chunked, the
Chunks are stored in SQLite and embedded in the vector store (fake embeddings, in memory), and one run of the extraction
LLM Graph retrieves them and makes a single model call. Observed through the upload API, the Audit Event and the stores."""

import io
import json
import re

import docx
import httpx
import pytest
from langchain_cohere import CohereRerank
from langchain_core.documents import Document
from langchain_core.vectorstores import InMemoryVectorStore
from sqlalchemy import select

from app import audit
from app.db import AuditEventRow, LlmExchangeRow, ReportChunkRow
from app.main import create_app
from app.prompts import RETRIEVAL_QUERIES
from app.report_index import NoRetryClientV2, get_reranker
from tests.fake_chat import FakeChatModel, serve_chat
from tests.fake_index import FakeReranker
from tests.uploads import upload

DEMO_PASSAGES = {
    "We are constructive on technology.",
    "Utilities look expensive after the rally and offer limited upside from here.",
    "We prefer equities over bonds for the next twelve months as growth stays resilient.",
}


def demo_docx() -> bytes:
    """The demo house view as a DOCX: headings, paragraphs and a table."""
    d = docx.Document()
    d.add_heading("Northwind House View, Q4 2026", 1)
    d.add_heading("Sectors", 2)
    d.add_paragraph(
        "We are constructive on technology. Earnings revisions remain strong and balance sheets are healthy."
    )
    d.add_paragraph("Utilities look expensive after the rally and offer limited upside from here.")
    table = d.add_table(rows=2, cols=2)
    for cell, text in zip(table._cells, ["Sector", "View", "Technology", "Positive"], strict=True):
        cell.text = text
    d.add_heading("Asset allocation", 2)
    d.add_paragraph("We prefer equities over bonds for the next twelve months as growth stays resilient.")
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def extracted_event(app, report_id) -> AuditEventRow:
    with app.state.session_factory() as db:
        return db.scalars(
            select(AuditEventRow).where(AuditEventRow.report_id == report_id, AuditEventRow.type == "insight_extracted")
        ).one()


def chunk_rows(app, report_id) -> list[ReportChunkRow]:
    with app.state.session_factory() as db:
        return list(
            db.scalars(
                select(ReportChunkRow).where(ReportChunkRow.report_id == report_id).order_by(ReportChunkRow.chunk_index)
            )
        )


@pytest.fixture(params=["markdown", "docx"])
def upload_demo(request, login):
    def go(**params):
        c = login("research_analyst")
        if request.param == "markdown":
            return upload(c, "house_view_demo.md", **params)
        return upload(c, "house_view_demo.docx", demo_docx(), **params)

    return go


def test_upload_stores_chunks_and_the_insights_cite_them(app, upload_demo):
    r = upload_demo()
    assert r.status_code == 201, r.text
    report = r.json()
    chunks = {c.id: c for c in chunk_rows(app, report["id"])}
    assert chunks and all(c.page == 1 and c.text.strip() for c in chunks.values())
    assert {i["passage"] for i in report["insights"]} == DEMO_PASSAGES
    for insight in report["insights"]:
        assert insight["chunk_id"] in chunks and insight["page"] == chunks[insight["chunk_id"]].page
        assert insight["passage"] in chunks[insight["chunk_id"]].text
        assert insight["status"] == "pending"
    assert any("Asset allocation" in c.headings for c in chunks.values())


def test_chunks_are_embedded_in_the_vector_store_with_flat_metadata(app, upload_demo):
    report = upload_demo().json()
    store = app.state.report_index.vector_store
    rows = {c.id: c for c in chunk_rows(app, report["id"])}
    docs = store.similarity_search("technology", k=50, filter=app.state.report_index.report_filter(report["id"]))
    assert {d.id for d in docs} == set(rows)
    for d in docs:
        assert d.metadata["report_id"] == report["id"] and d.metadata["page"] == 1
        assert all(isinstance(v, str | int) for v in d.metadata.values())  # flat: Chroma rejects anything nested
        assert d.page_content == rows[d.id].text
    other = store.similarity_search("technology", k=50, filter=app.state.report_index.report_filter("RPT-other"))
    assert other == []


def test_docx_tables_are_chunked_as_markdown(app, login):
    report = upload(login("research_analyst"), "house_view_demo.docx", demo_docx()).json()
    assert any("| Technology" in c.text for c in chunk_rows(app, report["id"]))


def test_extraction_is_one_exchange_and_the_event_carries_retrieval_provenance(app, upload_demo):
    report = upload_demo().json()
    with app.state.session_factory() as db:
        assert db.scalars(select(LlmExchangeRow)).all().__len__() == 1
        exchange = db.scalars(select(LlmExchangeRow)).one()
        assert audit.verify(db).valid
    assert (exchange.task, exchange.prompt_version, exchange.graph_node) == (
        "insight_extraction",
        "insight_extraction@v2",
        "generate",
    )
    # the Exchange records the prompt the model was sent: the Chunks, each under its id
    chunk_ids = {c.id for c in chunk_rows(app, report["id"])}
    assert set(re.findall(r"\[Chunk ([0-9a-f-]{36})\]", exchange.user_prompt)) == chunk_ids

    payload = json.loads(extracted_event(app, report["id"]).payload_json)
    assert payload["exchanges"] == [{"exchange_id": exchange.id, "exchange_hash": exchange.hash}]
    retrieval = payload["retrieval"]
    assert retrieval["query_version"] == RETRIEVAL_QUERIES.label
    assert retrieval["embedding_model"] == "openai/text-embedding-3-small"
    assert retrieval["chunker"]["max_tokens"] == 512
    assert set(retrieval["sent_chunk_ids"]) == chunk_ids
    runs = retrieval["retrievals"]
    assert len(runs) == 14  # one per taxonomy subject: 11 GICS sectors and 3 Asset Classes
    assert "Utilities sector" in next(r["query"] for r in runs if "Utilities" in r["query"])
    assert "equity as an asset class" in runs[11]["query"]
    for run in runs:
        assert {c["chunk_id"] for c in run["retrieved"]} <= chunk_ids
        assert [c["rank"] for c in run["retrieved"]] == list(range(1, len(run["retrieved"]) + 1))


def test_retrieval_is_limited_to_k_chunks_per_query(app, login):
    app.state.settings.retrieval_k = 1
    report = upload(login("research_analyst"), "house_view_demo.md").json()
    runs = json.loads(extracted_event(app, report["id"]).payload_json)["retrieval"]["retrievals"]
    assert all(len(r["retrieved"]) == 1 for r in runs)


def test_fabricated_chunk_ids_and_passages_are_dropped_with_reasons(app, login):
    def fabricate(request):
        real = next(
            block[:36] for block in request.user_prompt.split("[Chunk ")[1:] if "Utilities look expensive" in block
        )
        good = {"subject_kind": "sector", "subject": "Utilities", "direction": "negative", "confidence": "low"}
        return {
            "insights": [
                {
                    **good,
                    "chunk_id": real,
                    "passage": "Utilities look expensive after the rally and offer limited upside from here.",
                },
                {**good, "chunk_id": "11111111-1111-1111-1111-111111111111", "passage": "Utilities look expensive."},
                {**good, "chunk_id": real, "passage": "Utilities will triple."},
            ]
        }

    serve_chat(app, FakeChatModel(fabricate))
    report = upload(login("research_analyst"), "house_view_demo.md").json()
    assert [i["passage"] for i in report["insights"]] == [
        "Utilities look expensive after the rally and offer limited upside from here."
    ]
    dropped = json.loads(extracted_event(app, report["id"]).payload_json)["dropped"]
    assert [d["reason"] for d in dropped] == [
        "cited chunk was not among the chunks sent",
        "passage not found in cited chunk",
    ]


def test_a_retrieval_failure_fails_the_extraction_like_an_llm_failure(app, login, monkeypatch):
    def boom(self, query, k=4, **kwargs):
        raise ConnectionError("the vector store is down")

    monkeypatch.setattr(InMemoryVectorStore, "similarity_search", boom)
    model = serve_chat(app, FakeChatModel({"insights": []}))
    r = upload(login("research_analyst"), "house_view_demo.md")
    assert r.status_code == 201
    report = r.json()
    assert report["extraction_status"] == "failed" and report["insights"] == []
    assert "Retrieval failed" in report["extraction_error"] and "the vector store is down" in report["extraction_error"]
    assert model.requests == []  # no model call was made
    payload = json.loads(extracted_event(app, report["id"]).payload_json)
    assert payload["outcome"] == "failed" and "vector store is down" in payload["error"]
    with app.state.session_factory() as db:
        assert audit.verify(db).valid


def test_an_embedding_failure_fails_the_extraction_but_keeps_the_chunks(app, login, monkeypatch):
    def boom(self, texts):
        raise ConnectionError("the embedding endpoint is unreachable")

    monkeypatch.setattr(type(app.state.report_index.vector_store.embedding), "embed_documents", boom)
    report = upload(login("research_analyst"), "house_view_demo.md").json()
    assert report["extraction_status"] == "failed" and "embedding endpoint" in report["extraction_error"]
    assert chunk_rows(app, report["id"])  # SQLite is the record of truth: the Chunks are kept for a re-index


def test_unsupported_upload_types_are_rejected(login):
    assert upload(login("research_analyst"), "slides.key", b"x").status_code == 422


@pytest.mark.parametrize("name,content", [("scan.png", b"not a png"), ("photo.jpg", b"not a jpeg")])
def test_a_file_that_is_not_the_image_it_claims_to_be_is_rejected(login, name, content):
    assert upload(login("research_analyst"), name, content).status_code == 422


def test_provenance_shows_the_candidates_and_the_reranked_chunks_with_scores(app, login):
    app.state.settings.retrieval_k = 3
    app.state.settings.rerank_top_n = 2
    app.state.report_index.reranker = None  # rebuilt from the (fake) factory with the new top_n
    report = upload(login("research_analyst"), "house_view_demo.docx", demo_docx()).json()
    retrieval = json.loads(extracted_event(app, report["id"]).payload_json)["retrieval"]
    assert retrieval["rerank_model"] == "rerank-v3.5" and retrieval["rerank_top_n"] == 2
    runs = retrieval["retrievals"]
    assert len(runs) == 14  # the candidate retrieval is not a second run
    for run in runs:
        candidates = {c["chunk_id"] for c in run["candidates"]}
        assert len(run["candidates"]) <= 3 and len(run["retrieved"]) == min(2, len(candidates))
        assert {c["chunk_id"] for c in run["retrieved"]} <= candidates
        assert [c["rank"] for c in run["retrieved"]] == list(range(1, len(run["retrieved"]) + 1))
        scores = [c["relevance_score"] for c in run["retrieved"]]
        assert scores == sorted(scores, reverse=True)
    assert set(retrieval["sent_chunk_ids"]) == {c["chunk_id"] for r in runs for c in r["retrieved"]}


def test_a_rerank_failure_fails_the_extraction(app, login):
    app.state.report_index.reranker = FakeReranker(fail=True, calls=[])
    r = upload(login("research_analyst"), "house_view_demo.md")
    assert r.status_code == 201 and r.json()["extraction_status"] == "failed" and r.json()["insights"] == []
    payload = json.loads(extracted_event(app, r.json()["id"]).payload_json)
    assert payload["outcome"] == "failed" and "Retrieval failed: ConnectionError" in payload["error"]


def test_cohere_gets_one_request_per_query_and_is_never_retried():
    requests = []

    def overloaded(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(503, json={"message": "overloaded"})

    client = NoRetryClientV2("key", httpx_client=httpx.Client(transport=httpx.MockTransport(overloaded)))
    reranker = CohereRerank(model="rerank-v3.5", top_n=4, client=client)
    with pytest.raises(Exception, match="503|overloaded"):
        reranker.compress_documents([Document("a passage", metadata={})], "a query")
    assert len(requests) == 1  # the SDK's own default is two retries


def test_cohere_key_is_required_for_a_live_backend(settings):
    with pytest.raises(RuntimeError, match="APP_COHERE_API_KEY"):
        get_reranker(settings)
    settings.llm_api_key = "sk-live"
    with pytest.raises(RuntimeError, match="APP_COHERE_API_KEY"):
        create_app(settings)
    settings.cohere_api_key = "co-live"
    assert isinstance(get_reranker(settings), CohereRerank)
    create_app(settings)
