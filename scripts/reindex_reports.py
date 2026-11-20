"""Re-indexes existing Reports into the Report Index (ADR-0012).

    uv run python -m scripts.reindex_reports             # chunk and embed every Report that has no Chunks
    uv run python -m scripts.reindex_reports --rebuild   # drop the vector collection, re-embed it from SQLite

A Report from before the Report Index (a seeded one, or one uploaded earlier) has page texts but no Chunks. The first
form chunks those page texts through Docling's Markdown path, keeping page numbers, writes the `report_chunk` rows and
embeds them. Chunk ids are uuid5 of the Report and the index, so a rerun gives the same Chunks and an interrupted run
upserts. `--rebuild` proves the vector store is disposable: SQLite holds the Chunks, so it re-embeds them all and never
re-chunks. Neither form touches Insights or Audit Events.
"""

import argparse
import logging
from itertools import groupby

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import ReportChunkRow, ReportPageRow, ReportRow, make_session_factory
from app.report_index import ReportChunk, ReportError, ReportIndex, build_converter, chunk_pages
from app.settings import Settings

log = logging.getLogger("reindex_reports")
INDEXABLE = ("complete", "seeded")  # a pending Report is still being ingested; a failed one has no usable text


def reindex(session_factory: sessionmaker, index: ReportIndex) -> set[str]:
    """Chunks and embeds each Report that has no Chunks. Returns the ids of the Reports it indexed."""
    converter = build_converter()
    indexed: set[str] = set()
    with session_factory() as db:
        todo = db.scalars(
            select(ReportRow)
            .where(ReportRow.extraction_status.in_(INDEXABLE), ~ReportRow.id.in_(select(ReportChunkRow.report_id)))
            .order_by(ReportRow.id)
        ).all()
        for report in todo:
            pages = db.scalars(
                select(ReportPageRow.text).where(ReportPageRow.report_id == report.id).order_by(ReportPageRow.page)
            ).all()
            try:
                chunks = chunk_pages(
                    list(pages),
                    report_id=report.id,
                    embedding_model=index.settings.embedding_model,
                    converter=converter,
                )
            except ReportError as e:
                log.warning("%s: skipped (%s)", report.id, e)
                continue
            index.add(report.id, chunks)  # embed first: it is an upsert, so a crash before the commit is safe to rerun
            db.add_all(
                ReportChunkRow(
                    id=c.id, report_id=report.id, chunk_index=c.index, page=c.page, headings=c.headings, text=c.text
                )
                for c in chunks
            )
            db.commit()
            indexed.add(report.id)
            log.info("%s: %d Chunks", report.id, len(chunks))
    return indexed


def rebuild(session_factory: sessionmaker, index: ReportIndex) -> int:
    """Drops the vector collection and re-embeds every Chunk in SQLite. Returns the number of Chunks."""
    index.drop()
    total = 0
    with session_factory() as db:
        rows = db.scalars(select(ReportChunkRow).order_by(ReportChunkRow.report_id, ReportChunkRow.chunk_index))
        for report_id, group in groupby(rows, key=lambda r: r.report_id):
            chunks = [
                ReportChunk(id=r.id, index=r.chunk_index, page=r.page, headings=r.headings, text=r.text) for r in group
            ]
            index.add(report_id, chunks)
            total += len(chunks)
    return total


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--rebuild", action="store_true", help="drop the vector collection and re-embed it from SQLite")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings()
    session_factory = make_session_factory(settings.database_url)
    index = ReportIndex(settings)
    if args.rebuild:
        log.info("Rebuilt the vector store: %d Chunks", rebuild(session_factory, index))
    else:
        log.info("Indexed %d Reports", len(reindex(session_factory, index)))


if __name__ == "__main__":
    main()
