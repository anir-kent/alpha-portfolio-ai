"""Seam: re-indexing existing Reports (ADR-0012). `scripts.reindex_reports` chunks the stored page texts of Reports that
have no Chunks, writes `report_chunk` rows and embeds them; it is idempotent, and `--rebuild` restores the vector store
from SQLite alone. Run on the seeded Reports, offline (fake embeddings, in-memory vector store)."""

from sqlalchemy import func, select

from app.db import AuditEventRow, InsightRow, ReportChunkRow, ReportRow
from app.research_seed import seed_research
from scripts import reindex_reports

QUERIES = ["technology earnings", "utilities valuation", "equities over bonds", "energy outlook"]


def snapshot(app) -> list[tuple]:
    with app.state.session_factory() as db:
        rows = db.scalars(select(ReportChunkRow).order_by(ReportChunkRow.report_id, ReportChunkRow.chunk_index))
        return [(r.id, r.report_id, r.chunk_index, r.page, r.headings, r.text) for r in rows]


def untouched(app) -> tuple[int, int]:
    with app.state.session_factory() as db:
        return db.scalar(select(func.count(InsightRow.id))) or 0, db.scalar(select(func.count(AuditEventRow.id))) or 0


def retrieval(app) -> dict[str, list[list[str]]]:
    """The chunk ids each query retrieves from each seeded Report, in rank order."""
    index = app.state.report_index
    with app.state.session_factory() as db:
        report_ids = list(db.scalars(select(ReportRow.id).order_by(ReportRow.id)))
    return {
        r: [
            [
                d.metadata["chunk_id"]
                for d in index.vector_store.similarity_search(q, k=4, filter=index.report_filter(r))
            ]
            for q in QUERIES
        ]
        for r in report_ids
    }


def seeded(app) -> None:
    seed_research(app.state.session_factory, app.state.settings.seed_dir)


def test_reindex_chunks_every_seeded_report_keeping_pages(app):
    seeded(app)
    insights_and_events = untouched(app)
    assert snapshot(app) == []  # the seed stores pages only

    indexed = reindex_reports.reindex(app.state.session_factory, app.state.report_index)

    rows = snapshot(app)
    with app.state.session_factory() as db:
        reports = {r.id: r.page_count for r in db.scalars(select(ReportRow))}
    assert indexed == set(reports) and {r[1] for r in rows} == set(reports)
    for report_id, page_count in reports.items():
        mine = [r for r in rows if r[1] == report_id]
        assert [r[2] for r in mine] == list(range(len(mine)))  # chunk_index is contiguous per Report
        assert all(1 <= r[3] <= page_count for r in mine)  # pages are real pages
        assert [r[3] for r in mine] == sorted(r[3] for r in mine)
    assert untouched(app) == insights_and_events  # Insights and Audit Events are not touched


def test_every_chunk_is_embedded_under_its_id(app):
    seeded(app)
    reindex_reports.reindex(app.state.session_factory, app.state.report_index)

    ids = [r[0] for r in snapshot(app)]
    stored = app.state.report_index.vector_store.get_by_ids(ids)
    assert sorted(d.metadata["chunk_id"] for d in stored) == sorted(ids)


def test_running_twice_gives_the_same_chunks_and_ids(app):
    seeded(app)
    reindex_reports.reindex(app.state.session_factory, app.state.report_index)
    first, first_retrieval = snapshot(app), retrieval(app)

    assert reindex_reports.reindex(app.state.session_factory, app.state.report_index) == set()  # nothing left to do
    assert snapshot(app) == first
    assert retrieval(app) == first_retrieval


def test_a_rerun_after_a_partial_run_upserts_instead_of_duplicating(app):
    """Chunks already embedded but with no rows (a run that died before its commit) are overwritten by id, not doubled."""
    seeded(app)
    index = app.state.report_index
    reindex_reports.reindex(app.state.session_factory, index)
    first, first_retrieval = snapshot(app), retrieval(app)
    with app.state.session_factory() as db:
        db.query(ReportChunkRow).delete()
        db.commit()

    reindex_reports.reindex(app.state.session_factory, index)

    assert snapshot(app) == first
    assert retrieval(app) == first_retrieval


def test_rebuild_restores_the_vector_store_from_sqlite(app):
    seeded(app)
    index = app.state.report_index
    reindex_reports.reindex(app.state.session_factory, index)
    rows, before = snapshot(app), retrieval(app)

    reindex_reports.rebuild(app.state.session_factory, index)

    assert snapshot(app) == rows
    assert retrieval(app) == before


def test_rebuild_drops_vectors_that_no_row_backs(app):
    seeded(app)
    index = app.state.report_index
    reindex_reports.reindex(app.state.session_factory, index)
    before = retrieval(app)
    stale = index.vector_store.add_texts(
        ["a stale vector"], metadatas=[{"report_id": "RPT-FID-Q2-2026"}], ids=["stale"]
    )

    reindex_reports.rebuild(app.state.session_factory, index)

    assert index.vector_store.get_by_ids(stale) == []
    assert retrieval(app) == before
