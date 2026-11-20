"""Seam: the optional RAGAS script (`scripts.eval_ragas`, ADR-0012). Building a labelled view's Sample from the
extraction's provenance and rendering the report are checked without `ragas`, which is not a test dependency."""

from app.extraction import retrieval_queries
from app.settings import Settings
from scripts.eval_ragas import Sample, Scores, average_text, build_samples, render
from tests.fixtures.retrieval_eval import LABELS


def test_a_sample_holds_the_chunks_the_reranker_kept_and_the_insight_found(app):
    label = LABELS[0]
    query = next(q.text for q in retrieval_queries() if q.subject == label.subject)
    retrievals = [{"query": query, "retrieved": [{"chunk_id": "c2"}, {"chunk_id": "c1"}, {"chunk_id": "gone"}]}]
    [sample] = build_samples(
        label.report_id,
        [label],
        retrievals,
        {"c1": "one", "c2": "two"},
        {label.subject: (label.direction, "quoted")},
    )
    assert sample.user_input == query
    assert sample.retrieved_contexts == ["two", "one"]
    assert label.subject in (sample.response or "") and "quoted" in (sample.response or "")
    assert label.passage in sample.reference and label.direction in sample.reference


def test_a_view_the_model_did_not_report_has_no_response(app):
    [sample] = build_samples(LABELS[0].report_id, [LABELS[0]], [], {}, {})
    assert sample.response is None and sample.retrieved_contexts == []


def test_the_report_averages_what_was_scored_and_skips_the_rest():
    sample = Sample("RPT-1", "Energy", "q", [], None, "ref")
    scores = [
        Scores(sample, {"context_recall": 1.0, "faithfulness": float("nan")}),
        Scores(sample, {"context_recall": 0.5}),
    ]
    assert average_text(scores, "context_recall") == "0.750 (n=2)"
    assert average_text(scores, "faithfulness") == "n/a"
    text = render(Settings(), scores)
    assert "not Exchanges" in text and "| RPT-1 | Energy | no |" in text
