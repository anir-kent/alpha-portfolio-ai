"""Optional RAGAS evaluation of the Insight extraction graph (ADR-0012): faithfulness, context precision and context recall.

    uv sync --extra eval
    uv run --extra eval python -m scripts.eval_ragas [--report RPT-...] [--out PATH]

Run from the repo root with `APP_LLM_API_KEY` and `APP_COHERE_API_KEY` set. It seeds the Reports into a throwaway
database, chunks and embeds them in memory, runs the extraction graph once per Report and scores each labelled view
(`tests.fixtures.retrieval_eval.LABELS`, human-verified):

- user input: the view's Retrieval Query; retrieved contexts: the Chunks the reranker kept for it;
- response: the Insight the extraction kept for that subject (views the model did not report are scored for context
  only); reference: the labelled passage and direction.

The judge is `get_chat_model(settings)` (the app's chat model) and the embeddings are the app's `get_embeddings`, both
through RAGAS's LangChain wrappers. `ragas` is an optional dependency (`eval` extra): the main install and the test suite
do not need it.

**These calls are not Exchanges and are not audited.** RAGAS's judge calls bypass the LLM layer entirely. The extraction
run goes through `ModelLlm`, but into a throwaway database that is discarded. Nothing here reaches the app's database or
its Audit Trail. Its output is the Markdown report only. It makes hundreds of provider calls,
and Cohere rerank calls are throttled for a Trial key (`RERANK_INTERVAL_SECONDS`, 0 for a Production key).
"""

import argparse
import logging
import tempfile
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean
from typing import Any, cast

from langchain_core.vectorstores import InMemoryVectorStore
from pydantic import ValidationError
from sqlalchemy import select

from app.chat_model import get_chat_model
from app.db import ReportChunkRow, ReportPageRow, ReportRow, make_session_factory
from app.exchanges import build_llm
from app.extraction import check_insights, retrieval_queries, run_extraction
from app.llm import LlmError
from app.report_index import ReportIndex, get_embeddings, get_reranker
from app.reports import Extraction
from app.research_seed import seed_research
from app.settings import Settings
from scripts.reindex_reports import reindex
from tests.fixtures.retrieval_eval import LABELS, Label, Throttled

log = logging.getLogger("eval_ragas")
OUT = Path(".scratch/rag-insight-extraction/ragas.md")
METRICS = ("faithfulness", "llm_context_precision_with_reference", "context_recall")


@dataclass
class Sample:
    """One labelled view as RAGAS sees it."""

    report_id: str
    subject: str
    user_input: str
    retrieved_contexts: list[str]
    response: str | None  # the kept Insight, rendered as a sentence; None when the model reported no view
    reference: str


@dataclass
class Scores:
    """Per-metric scores of one Sample; a metric RAGAS could not score is missing or NaN."""

    sample: Sample
    values: dict[str, float | None] = field(default_factory=dict)


def render_insight(subject: str, direction: str, passage: str) -> str:
    return f'The Report\'s view on {subject} is {direction}: "{passage}"'


def render_reference(label: Label) -> str:
    return render_insight(label.subject, label.direction, label.passage)


def build_samples(
    report_id: str,
    labels: list[Label],
    retrievals: list[dict],
    chunk_text: dict[str, str],
    insights: dict[str, tuple[str, str]],
) -> list[Sample]:
    """A Sample for each label of the Report. `retrievals` is the Retrieval Provenance (the Chunks each query kept),
    `chunk_text` maps a Chunk id to its text and `insights` the kept Insights by subject to (direction, passage)."""
    by_query = {r["query"]: r for r in retrievals}
    queries = {q.subject: q.text for q in retrieval_queries()}
    samples = []
    for label in labels:
        query = queries[label.subject]
        kept = by_query.get(query, {}).get("retrieved", [])
        found = insights.get(label.subject)
        samples.append(
            Sample(
                report_id,
                label.subject,
                query,
                [chunk_text[c["chunk_id"]] for c in kept if c["chunk_id"] in chunk_text],
                render_insight(label.subject, *found) if found else None,
                render_reference(label),
            )
        )
    return samples


def run_report(llm, index: ReportIndex, report_id: str, pages: list[str], chunk_text: dict[str, str]) -> list[Sample]:
    """Runs the extraction graph on one Report and returns its labelled views as Samples."""
    labels = [label for label in LABELS if label.report_id == report_id]
    if not labels:
        return []
    insights: dict[str, tuple[str, str]] = {}
    try:
        response, sent, record = run_extraction(llm, index, report_id)
        kept, _ = check_insights(Extraction.model_validate(response.content), sent, pages)
    except (LlmError, ValidationError) as e:
        log.warning("%s: extraction failed, Report skipped: %s", report_id, str(e)[:200])
        return []
    for c in kept:
        insights[c.insight.subject] = (c.insight.direction, c.insight.passage)
    return build_samples(report_id, labels, record["retrievals"], chunk_text, insights)


def score(samples: list[Sample], settings: Settings) -> list[Scores]:
    """Scores the Samples with RAGAS: context precision and recall on all of them, faithfulness on those with a response.
    `ragas` is imported here so the rest of the module (and the test suite) works without it."""
    try:
        with warnings.catch_warnings():
            # The LangChain wrappers and `ragas.metrics` are the documented path for a LangChain app (ragas 0.4).
            warnings.simplefilter("ignore", DeprecationWarning)
            from ragas import EvaluationDataset, evaluate
            from ragas.dataset_schema import SingleTurnSample
            from ragas.embeddings import LangchainEmbeddingsWrapper
            from ragas.llms import LangchainLLMWrapper
            from ragas.metrics import Faithfulness, LLMContextPrecisionWithReference, LLMContextRecall
    except ImportError as e:
        raise SystemExit("ragas is not installed: run with `uv run --extra eval python -m scripts.eval_ragas`") from e

    # RAGAS sets a temperature on every judge call; the app's model (Claude 5 via OpenRouter) accepts none.
    with warnings.catch_warnings():
        warnings.simplefilter(
            "ignore", DeprecationWarning
        )  # ragas 0.4 prefers its own client factories; these still work
        judge = LangchainLLMWrapper(get_chat_model(settings), bypass_temperature=True)
        embeddings = LangchainEmbeddingsWrapper(get_embeddings(settings))

    def evaluate_rows(rows: list[Sample], metrics: list[Any]) -> list[dict[str, Any]]:
        dataset = EvaluationDataset(
            samples=[
                SingleTurnSample(
                    user_input=s.user_input,
                    retrieved_contexts=s.retrieved_contexts,
                    response=s.response or "",
                    reference=s.reference,
                )
                for s in rows
            ]
        )
        result = evaluate(dataset, metrics=metrics, llm=judge, embeddings=embeddings, show_progress=False)
        return cast(list[dict[str, Any]], result.scores)  # type: ignore[union-attr]  # an EvaluationResult here, not an Executor

    scored = [Scores(s) for s in samples]
    for row, result in zip(
        scored, evaluate_rows(samples, [LLMContextPrecisionWithReference(), LLMContextRecall()]), strict=True
    ):
        row.values.update(result)
    answered = [row for row in scored if row.sample.response]
    if answered:
        for row, result in zip(answered, evaluate_rows([r.sample for r in answered], [Faithfulness()]), strict=True):
            row.values.update(result)
    return scored


def scored(row: Scores, metric: str) -> float | None:
    """The row's score for the metric, or None when RAGAS gave none (missing or NaN)."""
    value = row.values.get(metric)
    return value if isinstance(value, float) and value == value else None


def average_text(scores: list[Scores], metric: str) -> str:
    values = [v for s in scores if (v := scored(s, metric)) is not None]
    return f"{mean(values):.3f} (n={len(values)})" if values else "n/a"


def render(settings: Settings, scores: list[Scores]) -> str:
    lines = [
        "# RAGAS evaluation of Insight extraction",
        "",
        f"Generated by `scripts/eval_ragas.py`. Judge and chat model `{settings.llm_model}`, embeddings `{settings.embedding_model}`, "
        f"rerank `{settings.rerank_model}`, k={settings.retrieval_k}, top_n={settings.rerank_top_n}. One row per labelled "
        "(human-verified) view: the Retrieval Query is the user input, the Chunks the reranker kept are the contexts, the "
        "kept Insight is the response and the labelled passage is the reference. Faithfulness is scored only where the "
        "model reported the view. Caveats: the judge is the same model that extracted (a self-judging bias), and the response and "
        "reference are rendered as a sentence around the quoted passage, which can lower faithfulness. A Report whose extraction "
        "failed is skipped. RAGAS's judge calls are not Exchanges and are not audited.",
        "",
        "| Metric | Mean |",
        "| --- | --- |",
        *(f"| {m} | {average_text(scores, m)} |" for m in METRICS),
        "",
        "| Report | Subject | Reported | " + " | ".join(METRICS) + " |",
        "| --- | --- | --- | " + " | ".join("---" for _ in METRICS) + " |",
    ]
    for s in scores:
        cells = [f"{v:.2f}" if (v := scored(s, m)) is not None else "n/a" for m in METRICS]
        lines.append(
            f"| {s.sample.report_id} | {s.sample.subject} | {'yes' if s.sample.response else 'no'} | "
            + " | ".join(cells)
            + " |"
        )
    return "\n".join(lines) + "\n"


def collect(settings: Settings, only: str | None = None) -> list[Sample]:
    with tempfile.TemporaryDirectory() as directory:
        session_factory = make_session_factory(f"sqlite:///{directory}/ragas.db")
        llm = build_llm(settings, session_factory)
        index = ReportIndex(settings)
        index.vector_store = InMemoryVectorStore(get_embeddings(settings))
        index.reranker = Throttled(inner=get_reranker(settings))
        seed_research(session_factory, settings.seed_dir)
        reindex(session_factory, index)
        samples: list[Sample] = []
        with session_factory() as db:
            chunk_text = {c.id: c.text for c in db.scalars(select(ReportChunkRow))}
            for report in (r for r in db.scalars(select(ReportRow).order_by(ReportRow.id)) if only in (None, r.id)):
                pages = list(
                    db.scalars(
                        select(ReportPageRow.text)
                        .where(ReportPageRow.report_id == report.id)
                        .order_by(ReportPageRow.page)
                    )
                )
                log.info("%s: extraction", report.id)
                samples += run_report(llm, index, report.id, pages, chunk_text)
    return samples


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", help="evaluate one Report (its id) instead of every seeded Report")
    parser.add_argument("--out", type=Path, default=OUT, help=f"where to write the Markdown report (default {OUT})")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings(vector_store="memory")
    samples = collect(settings, args.report)
    log.info("Scoring %d views with RAGAS", len(samples))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(settings, score(samples, settings)))
    log.info("Wrote %s", args.out)


if __name__ == "__main__":
    main()
