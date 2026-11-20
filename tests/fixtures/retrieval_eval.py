"""The retrieval eval set and its runner (ADR-0012). The labels are the seeded Reports' human-verified views: for each,
the subject the Retrieval Query asks about and the passage that states the view. The Chunks expected to hold it are the
ones whose text contains the passage, found after the Report is chunked, so the labels survive a change of chunker.

`run_eval` indexes the seeded Reports the way `scripts.reindex_reports` does, then runs each label's Retrieval Query
through the production retriever and scores it. Offline (fake embeddings and reranker) it is a smoke test of the
pipeline; with the real providers (`tests.test_retrieval_eval`, `-m live_eval`) it measures recall."""

import json
import os
import time
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from itertools import groupby
from pathlib import Path

from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app.db import ReportChunkRow
from app.extraction import RetrievalProvenance, report_retriever, retrieval_queries
from app.report_index import ReportIndex
from app.reports import passage_in_chunk
from scripts.reindex_reports import reindex

SEED_DIR = Path(__file__).resolve().parents[2] / "data" / "seed"
# What the live eval must reach (`EvalReport` metric -> floor): the measured values on 2026-11-20 (19 views: hit-rate@10
# 1.000, MRR 0.929, hit-rate@4 1.000, MRR after rerank 0.974, sent 1.000) with room for one miss, so a regression fails.
THRESHOLDS: dict[str, float] = {
    "hit_rate_at_k": 0.9,
    "mrr": 0.85,
    "hit_rate_at_top_n": 0.9,
    "mrr_reranked": 0.9,
    "sent_recall": 0.9,
}


class Throttled(BaseDocumentCompressor):
    """A reranker that waits so its calls are at least `interval` seconds apart: a Cohere Trial key allows 10 a minute, and
    an eval makes one call per Retrieval Query. `RERANK_INTERVAL_SECONDS` sets it (default 6.5; 0 for a Production key)."""

    inner: BaseDocumentCompressor
    interval: float = Field(default_factory=lambda: float(os.environ.get("RERANK_INTERVAL_SECONDS", "6.5")))
    last: float = 0.0

    def compress_documents(
        self, documents: Sequence[Document], query: str, callbacks: Callbacks | None = None
    ) -> Sequence[Document]:
        time.sleep(max(0.0, self.last + self.interval - time.monotonic()))
        try:
            return self.inner.compress_documents(documents, query, callbacks)
        finally:
            self.last = time.monotonic()


@dataclass(frozen=True)
class Label:
    report_id: str
    subject_kind: str
    subject: str
    passage: str  # verbatim in the Report, on `page`
    page: int
    direction: str  # positive | neutral | negative


_DIRECTION = {"overweight": "positive", "neutral": "neutral", "underweight": "negative"}


def load_labels(seed_dir: Path = SEED_DIR) -> list[Label]:
    """The seeded Insights (hand-written, and the hand-transcribed p3 scorecard), which are human-verified."""
    labels = [
        Label(i["report_id"], i["subject_kind"], i["subject"], i["passage"], i["page"], i["direction"])
        for i in json.loads((seed_dir / "insights.json").read_text())
    ]
    card = json.loads((seed_dir / "q2_scorecard_p3.json").read_text())
    labels += [
        Label(card["report_id"], "sector", r["sector"], r["comment"], card["page"], _DIRECTION[r["view"]])
        for r in card["rows"]
    ]
    return sorted(labels, key=lambda label: (label.report_id, label.subject))


LABELS = load_labels()


def reciprocal_rank(ranked: Sequence[str], expected: set[str]) -> tuple[int | None, float]:
    """(1-based rank of the first expected Chunk, its reciprocal), or (None, 0.0) when none is in the list."""
    for rank, chunk_id in enumerate(ranked, 1):
        if chunk_id in expected:
            return rank, 1 / rank
    return None, 0.0


@dataclass(frozen=True)
class LabelResult:
    label: Label
    expected: frozenset[str]  # ids of the Chunks that hold the passage
    candidate_rank: int | None  # of the first expected Chunk among the vector store's top k
    reranked_rank: int | None  # of the first expected Chunk among the reranker's top_n
    sent: bool  # an expected Chunk is in the union of what every query of the Report kept: what the model reads


@dataclass
class EvalReport:
    k: int
    top_n: int
    results: list[LabelResult] = field(default_factory=list)
    unresolved: list[Label] = field(default_factory=list)  # no Chunk holds the passage (the chunker split it)

    def _share(self, hit: Sequence[bool]) -> float:
        return sum(hit) / len(hit) if hit else 0.0

    def _mrr(self, ranks: Sequence[int | None]) -> float:
        return sum(1 / rank for rank in ranks if rank) / len(ranks) if ranks else 0.0

    @property
    def hit_rate_at_k(self) -> float:
        return self._share([r.candidate_rank is not None for r in self.results])

    @property
    def mrr(self) -> float:
        return self._mrr([r.candidate_rank for r in self.results])

    @property
    def hit_rate_at_top_n(self) -> float:
        return self._share([r.reranked_rank is not None for r in self.results])

    @property
    def mrr_reranked(self) -> float:
        return self._mrr([r.reranked_rank for r in self.results])

    @property
    def sent_recall(self) -> float:
        return self._share([r.sent for r in self.results])

    def summary(self) -> str:
        lines = [
            f"{len(self.results)} labelled views, {len(self.unresolved)} unresolved",
            f"before rerank: hit-rate@{self.k} {self.hit_rate_at_k:.3f}  MRR {self.mrr:.3f}",
            f"after rerank:  hit-rate@{self.top_n} {self.hit_rate_at_top_n:.3f}  MRR {self.mrr_reranked:.3f}",
            f"sent to the model (any query's top {self.top_n}): {self.sent_recall:.3f}",
        ]
        lines += [
            f"  miss: {r.label.report_id} {r.label.subject}: candidate rank {r.candidate_rank}, reranked {r.reranked_rank}"
            for r in self.results
            if r.reranked_rank is None
        ]
        return "\n".join(lines)


def run_eval(session_factory: sessionmaker, index: ReportIndex, labels: Sequence[Label] = LABELS) -> EvalReport:
    """Indexes the Reports that have no Chunks, then runs all the Retrieval Queries on each labelled Report, as an
    extraction does, and scores each label. The Reports must be stored."""
    reindex(session_factory, index)
    queries = retrieval_queries()
    report = EvalReport(k=index.settings.retrieval_k, top_n=index.settings.rerank_top_n)
    chunks: dict[str, list[tuple[str, str]]] = defaultdict(list)
    with session_factory() as db:
        for row in db.scalars(select(ReportChunkRow).order_by(ReportChunkRow.report_id, ReportChunkRow.chunk_index)):
            chunks[row.report_id].append((row.id, row.text))
    for report_id, group in groupby(
        sorted(labels, key=lambda label: label.report_id), key=lambda label: label.report_id
    ):
        retriever = report_retriever(
            index.vector_store, index.report_filter(report_id), index.reranker, index.settings.retrieval_k
        )
        provenance = RetrievalProvenance()
        for query in queries:
            retriever.invoke(query.text, {"callbacks": [provenance]})
        by_query = {r["query"]: r for r in provenance.retrievals}
        sent = {c["chunk_id"] for r in provenance.retrievals for c in r["retrieved"]}
        for label in group:
            expected = {cid for cid, text in chunks[report_id] if passage_in_chunk(label.passage, text)}
            if not expected:
                report.unresolved.append(label)
                continue
            run = by_query[next(q.text for q in queries if q.subject == label.subject)]
            candidate_rank, _ = reciprocal_rank([c["chunk_id"] for c in run["candidates"]], expected)
            reranked_rank, _ = reciprocal_rank([c["chunk_id"] for c in run["retrieved"]], expected)
            report.results.append(
                LabelResult(label, frozenset(expected), candidate_rank, reranked_rank, bool(expected & sent))
            )
    return report
