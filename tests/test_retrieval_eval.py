"""Seam: the retrieval eval (ADR-0012). For each seeded Report, each labelled subject's Retrieval Query goes through the
production retriever (vector store, then rerank) and is scored: hit-rate@k and MRR over the candidates, the same after
rerank, and the share of views whose Chunk reaches the model. Offline it runs on fake embeddings and a fake reranker, as a
smoke test of the pipeline and the metrics. `-m live_eval` runs it on the real embedding model and Cohere, against
thresholds."""

import pytest
from fastapi import FastAPI
from langchain_core.vectorstores import InMemoryVectorStore

from app.report_index import ReportIndex, chunk_tokenizer, get_embeddings, get_reranker
from app.research_seed import seed_research
from app.settings import Settings
from tests.fixtures.retrieval_eval import LABELS, THRESHOLDS, EvalReport, Throttled, reciprocal_rank, run_eval

# The real providers, bound before the `offline_index` fixture patches the module for each test.
REAL = (get_embeddings, get_reranker, chunk_tokenizer)
SYNTHETIC = {"RPT-HV-NORTHWIND-Q4-2026", "RPT-HV-HARBOR-Q4-2026", "RPT-HV-MERIDIAN-Q4-2026"}


def test_reciprocal_rank_is_one_over_the_first_expected_rank():
    assert reciprocal_rank(["a", "b", "c"], {"c", "b"}) == (2, 0.5)
    assert reciprocal_rank(["a"], {"a"}) == (1, 1.0)
    assert reciprocal_rank(["a", "b"], {"z"}) == (None, 0.0)
    assert reciprocal_rank([], {"a"}) == (None, 0.0)


def test_labels_cover_every_seeded_report():
    assert {label.report_id for label in LABELS} >= SYNTHETIC
    assert len({(label.report_id, label.subject) for label in LABELS}) == len(LABELS)


def run_offline(app: FastAPI) -> EvalReport:
    seed_research(app.state.session_factory, app.state.settings.seed_dir)
    return run_eval(app.state.session_factory, app.state.report_index)


def test_every_label_resolves_to_a_chunk_that_holds_its_passage(app):
    report = run_offline(app)
    assert report.unresolved == []
    assert len(report.results) == len(LABELS)
    assert all(r.expected for r in report.results)


def test_a_small_report_is_fully_retrieved_because_k_covers_all_its_chunks(app):
    report = run_offline(app)
    small = [r for r in report.results if r.label.report_id in SYNTHETIC]
    assert small and all(r.candidate_rank is not None for r in small)


def test_rerank_only_narrows_the_candidates(app):
    report = run_offline(app)
    assert report.k == app.state.settings.retrieval_k and report.top_n == app.state.settings.rerank_top_n
    for r in report.results:
        assert r.reranked_rank is None or (r.candidate_rank is not None and r.reranked_rank <= report.top_n)
    assert report.hit_rate_at_top_n <= report.hit_rate_at_k
    assert all(
        0.0 <= m <= 1.0 for m in (report.hit_rate_at_k, report.mrr, report.hit_rate_at_top_n, report.mrr_reranked)
    )
    assert report.sent_recall >= report.hit_rate_at_top_n  # a Chunk any query kept is sent, whichever query it was for


def test_the_eval_is_deterministic_offline(app):
    first = run_offline(app)
    again = run_eval(app.state.session_factory, app.state.report_index)
    assert [(r.candidate_rank, r.reranked_rank, r.sent) for r in first.results] == [
        (r.candidate_rank, r.reranked_rank, r.sent) for r in again.results
    ]


def test_the_summary_names_each_metric(app):
    text = run_offline(app).summary()
    for name in ("hit-rate@", "MRR", "sent"):
        assert name in text


@pytest.mark.live_eval
def test_live_retrieval_meets_the_thresholds(app, allow_network, monkeypatch):
    """Real embeddings and the real Cohere cross-encoder over the seeded Reports. Opt in with `-m live_eval`; needs
    `APP_LLM_API_KEY` and `APP_COHERE_API_KEY` (read from `.env`)."""
    embeddings, reranker, tokenizer = REAL
    monkeypatch.setattr("app.report_index.chunk_tokenizer", tokenizer)
    settings = Settings(vector_store="memory")
    index = ReportIndex(settings)
    index.vector_store = InMemoryVectorStore(embeddings(settings))
    index.reranker = Throttled(inner=reranker(settings))
    seed_research(app.state.session_factory, app.state.settings.seed_dir)
    report = run_eval(app.state.session_factory, index)
    print("\n" + report.summary())
    assert report.unresolved == []
    for metric, floor in THRESHOLDS.items():
        assert getattr(report, metric) >= floor, f"{metric} {getattr(report, metric):.3f} is under {floor}"
