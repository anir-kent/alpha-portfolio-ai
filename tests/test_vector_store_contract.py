"""Seam: the vector-store contract (ADR-0012). `get_vector_store` and `report_filter` give every backend the same
behaviour: add, search filtered to one Report, delete by id, uuid5 ids and flat metadata that round-trips. One suite runs
against each backend, offline, on fake embeddings."""

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding
from langchain_core.vectorstores import VectorStore

from app.report_index import ReportChunk, chunk_documents, chunk_id, drop_vector_store, get_vector_store, report_filter
from app.settings import Settings


@pytest.fixture(params=["memory", "chroma", "qdrant"])
def backend(request: pytest.FixtureRequest, tmp_path) -> tuple[Settings, VectorStore]:
    settings = Settings(vector_store=request.param, chroma_dir=str(tmp_path / "chroma"), qdrant_dir=":memory:")
    return settings, get_vector_store(settings, DeterministicFakeEmbedding(size=16))


def chunks(report_id: str) -> list[ReportChunk]:
    return [
        ReportChunk(
            id=chunk_id(report_id, i),
            index=i,
            page=i + 1,
            headings="Sectors > Technology",
            text=f"{report_id} text {i}",
        )
        for i in range(3)
    ]


def load(store: VectorStore) -> None:
    for report_id in ("RPT-a", "RPT-b"):
        report_chunks = chunks(report_id)
        store.add_documents(chunk_documents(report_id, report_chunks), ids=[c.id for c in report_chunks])


def test_search_is_confined_to_the_report(backend):
    settings, store = backend
    load(store)
    found = store.similarity_search("text", k=10, filter=report_filter(settings, "RPT-a"))
    assert {d.metadata["chunk_id"] for d in found} == {c.id for c in chunks("RPT-a")}
    assert {d.metadata["report_id"] for d in found} == {"RPT-a"}
    assert store.similarity_search("text", k=10, filter=report_filter(settings, "RPT-none")) == []


def test_metadata_is_flat_and_round_trips(backend):
    settings, store = backend
    load(store)
    doc = next(
        d
        for d in store.similarity_search("text 1", k=10, filter=report_filter(settings, "RPT-a"))
        if d.metadata["chunk_index"] == 1
    )
    assert doc.page_content == "RPT-a text 1"
    for key, value in {
        "report_id": "RPT-a",
        "chunk_id": chunk_id("RPT-a", 1),
        "chunk_index": 1,
        "page": 2,
        "headings": "Sectors > Technology",
    }.items():
        assert doc.metadata[key] == value
    assert all(isinstance(v, str | int) for v in doc.metadata.values() if v is not None)


def test_chunk_ids_are_stable_uuid5s(backend):
    settings, store = backend
    assert chunk_id("RPT-a", 1) == chunk_id("RPT-a", 1) != chunk_id("RPT-a", 2)
    load(store)
    load(store)  # re-indexing the same Report is idempotent
    found = store.similarity_search("text", k=50, filter=report_filter(settings, "RPT-a"))
    assert len(found) == 3
    assert [d.metadata["chunk_id"] for d in store.get_by_ids([chunk_id("RPT-a", 0)])] == [chunk_id("RPT-a", 0)]


def test_a_deleted_chunk_is_no_longer_found(backend):
    settings, store = backend
    load(store)
    gone = chunk_id("RPT-a", 0)
    store.delete(ids=[gone])
    found = store.similarity_search("text", k=10, filter=report_filter(settings, "RPT-a"))
    assert gone not in {d.metadata["chunk_id"] for d in found}
    assert len(found) == 2


def test_a_dropped_collection_comes_back_empty_and_usable(backend):
    settings, store = backend
    load(store)

    drop_vector_store(settings, store)

    fresh = get_vector_store(settings, DeterministicFakeEmbedding(size=16))
    assert fresh.get_by_ids([c.id for c in chunks("RPT-a")]) == []
    load(fresh)
    assert len(fresh.get_by_ids([c.id for c in chunks("RPT-a")])) == 3
