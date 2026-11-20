"""Seam: the one-off RAG vs full-text comparison (`scripts.compare_extraction`, ADR-0012). The grouping of what the two
paths found is checked directly; the script itself runs offline on the fakes, where it records a path's failure instead
of crashing, and writes its Markdown report."""

from pathlib import Path

from scripts import compare_extraction
from scripts.compare_extraction import PathResult, classify, seeded_recall


def found(**subjects: str) -> PathResult:
    return PathResult(insights={s: {d} for s, d in subjects.items()})


def test_each_subject_is_a_match_a_direction_difference_a_miss_or_an_extra():
    rag = found(Energy="negative", Utilities="positive", Materials="neutral")
    full = found(Energy="negative", Utilities="negative", Financials="positive")
    groups = classify(rag, full)
    assert groups["match"] == ["Energy (RAG negative, full text negative)"]
    assert groups["direction differs"] == ["Utilities (RAG positive, full text negative)"]
    assert groups["missed"] == ["Financials (positive)"]
    assert groups["extra"] == ["Materials (neutral)"]


def test_seeded_recall_counts_views_found_with_their_direction():
    seeded = {"Energy": "negative", "Utilities": "positive", "Financials": "positive"}
    assert seeded_recall(found(Energy="negative", Utilities="negative"), seeded) == "1/3"


def test_the_script_writes_a_report_even_where_a_path_fails(app, monkeypatch, tmp_path):
    settings = app.state.settings
    monkeypatch.setattr(compare_extraction, "Settings", lambda **kwargs: settings)
    monkeypatch.setattr(compare_extraction, "get_embeddings", lambda s: app.state.report_index.vector_store.embedding)
    monkeypatch.setattr(compare_extraction, "get_reranker", lambda s: app.state.report_index.reranker)
    monkeypatch.setattr(compare_extraction, "Throttled", lambda inner: inner)
    out = tmp_path / "comparison.md"
    compare_extraction.main(["--report", "RPT-HV-HARBOR-Q4-2026", "--out", str(out)])
    text = Path(out).read_text()
    assert "RPT-HV-HARBOR-Q4-2026" in text and "| Report |" in text
