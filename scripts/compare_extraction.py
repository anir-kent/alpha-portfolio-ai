"""One-off comparison of the two ways to extract Insights from a Report (ADR-0012): the RAG path (retrieve, rerank, one
generate call) against the full-text path it replaced (every page in one prompt, the pre-RAG `insight_extraction@v1`).

    uv run python -m scripts.compare_extraction [--report RPT-...] [--out PATH]

Run from the repo root with `APP_LLM_API_KEY` and `APP_COHERE_API_KEY` set. It seeds the Reports into a throwaway
database, chunks and embeds them in memory, runs both paths on each Report with the live models and writes a Markdown
report: which Insights match, which the RAG path missed, which it added, how each compares with the seeded (human-verified)
views, and how much text each path sent. Nothing is written to the app's database or vector store. It makes a few hundred
provider calls, and Cohere rerank calls are throttled for a Trial key (`RERANK_INTERVAL_SECONDS`, 0 for a Production key).
"""

import argparse
import logging
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.vectorstores import InMemoryVectorStore
from pydantic import BaseModel, ValidationError
from sqlalchemy import select

from app.db import ReportPageRow, ReportRow, make_session_factory
from app.exchanges import ModelLlm, build_llm
from app.extraction import check_insights, run_extraction
from app.llm import LlmError, LlmRequest
from app.report_index import ReportIndex, get_embeddings, get_reranker
from app.reports import Extraction, InsightFields, passage_on_page, valid_subject
from app.research_seed import seed_research
from app.settings import Settings
from scripts.reindex_reports import reindex
from tests.fixtures.retrieval_eval import LABELS, Throttled

log = logging.getLogger("compare_extraction")
OUT = Path(".scratch/rag-insight-extraction/comparison.md")

# `insight_extraction@v1`, the prompt the full-text path used before ADR-0012 (git: 098a1dc^, app/prompts.py).
FULL_TEXT_PROMPT = "insight_extraction@v1"
FULL_TEXT_SYSTEM = """You extract investment Insights from a research Report for a wealth-management platform.

The Report is given as pages, each introduced by a line "[Page N]". Return ONLY a JSON object:
{"insights": [{"subject_kind": "sector" | "asset_class", "subject": string, "direction": "positive" | "neutral" | "negative",
"confidence": "low" | "medium" | "high", "page": integer, "passage": string}]}

Rules:
- subject_kind "sector": subject must be exactly one of the GICS sectors: Communication Services, Consumer Discretionary,
  Consumer Staples, Energy, Financials, Health Care, Industrials, Information Technology, Materials, Real Estate, Utilities.
- subject_kind "asset_class": subject must be exactly one of: equity, bond, cash.
- direction is the Report's view on the subject; confidence reflects how strongly and consistently the Report supports it.
- "page" is the page the passage appears on and "passage" is a verbatim quote from that page (one or two sentences).
  Never paraphrase, never invent text, never cite a page you did not read.
- Report only views the Report actually states. Do not compute or restate numbers of your own.
- If the Report states no usable view, return {"insights": []}."""


class PagedInsight(InsightFields):
    page: int


class PagedExtraction(BaseModel):
    insights: list[PagedInsight]


@dataclass
class PathResult:
    """What one path produced for one Report: the kept Insights as (subject, direction), what it sent, and any failure."""

    insights: dict[str, set[str]] = field(default_factory=dict)
    dropped: int = 0
    chars_sent: int = 0
    error: str | None = None


@dataclass
class ReportComparison:
    report_id: str
    title: str
    pages: int
    rag: PathResult
    full: PathResult
    seeded: dict[str, str]  # the human-verified views: subject -> direction
    chunks_sent: int = 0
    chunks_total: int = 0


def run_rag(llm: ModelLlm, index: ReportIndex, report_id: str, pages: list[str]) -> tuple[PathResult, int]:
    result = PathResult()
    try:
        response, sent, _ = run_extraction(llm, index, report_id)
        kept, dropped = check_insights(Extraction.model_validate(response.content), sent, pages)
    except (LlmError, ValidationError) as e:
        result.error = str(e)[:300]
        return result, 0
    for c in kept:
        result.insights.setdefault(c.insight.subject, set()).add(c.insight.direction)
    result.dropped, result.chars_sent = len(dropped), sum(len(c.text) for c in sent)
    return result, len(sent)


def run_full_text(llm: ModelLlm, pages: list[str]) -> PathResult:
    user = "\n\n".join(f"[Page {n}]\n{text.strip()}" for n, text in enumerate(pages, 1))
    request = LlmRequest(
        "insight_extraction", FULL_TEXT_PROMPT, FULL_TEXT_SYSTEM, user, PagedExtraction.model_json_schema()
    )
    result = PathResult(chars_sent=len(user))
    try:
        extraction = PagedExtraction.model_validate(llm.complete(request).content)
    except (LlmError, ValidationError) as e:
        result.error = str(e)[:300]
        return result
    for i in extraction.insights:
        on_page = 1 <= i.page <= len(pages) and passage_on_page(i.passage, pages[i.page - 1])
        if valid_subject(i.subject_kind, i.subject) and on_page:
            result.insights.setdefault(i.subject, set()).add(i.direction)
        else:
            result.dropped += 1
    return result


def classify(rag: PathResult, full: PathResult) -> dict[str, list[str]]:
    """Each subject either path found, as match (same direction), direction differs, missed (full text only) or extra
    (RAG only)."""
    groups: dict[str, list[str]] = defaultdict(list)
    for subject in sorted(rag.insights.keys() | full.insights.keys()):
        r, f = rag.insights.get(subject), full.insights.get(subject)
        if r and f:
            groups["match" if r & f else "direction differs"].append(
                f"{subject} (RAG {'/'.join(sorted(r))}, full text {'/'.join(sorted(f))})"
            )
        elif f:
            groups["missed"].append(f"{subject} ({'/'.join(sorted(f))})")
        else:
            groups["extra"].append(f"{subject} ({'/'.join(sorted(r or set()))})")
    return groups


def seeded_recall(path: PathResult, seeded: dict[str, str]) -> str:
    found = sum(direction in path.insights.get(subject, set()) for subject, direction in seeded.items())
    return f"{found}/{len(seeded)}"


def render(settings: Settings, comparisons: list[ReportComparison]) -> str:
    lines = [
        "# RAG vs full-text Insight extraction",
        "",
        f"Generated by `scripts/compare_extraction.py`. Chat model `{settings.llm_model}`, embeddings `{settings.embedding_model}`, "
        f"rerank `{settings.rerank_model}`, k={settings.retrieval_k}, top_n={settings.rerank_top_n}, "
        "retrieval queries v1. *Match*: both paths found the subject with the same direction. *Missed*: only the full-text path "
        "did. *Extra*: only the RAG path did. *Seeded* is the human-verified views of the seeded Report (where it has any).",
        "",
        "| Report | Pages | Seeded views found (RAG / full text) | Match | Direction differs | Missed | Extra | Text sent (RAG / full text) |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    details = []
    for c in comparisons:
        groups = classify(c.rag, c.full)
        seeded = f"{seeded_recall(c.rag, c.seeded)} / {seeded_recall(c.full, c.seeded)}" if c.seeded else "n/a"
        sent = f"{c.rag.chars_sent:,} / {c.full.chars_sent:,} chars ({c.chunks_sent}/{c.chunks_total} Chunks)"
        lines.append(
            f"| {c.report_id} | {c.pages} | {seeded} | {len(groups['match'])} | {len(groups['direction differs'])} "
            f"| {len(groups['missed'])} | {len(groups['extra'])} | {sent} |"
        )
        details += [f"## {c.report_id}", f"{c.title}", ""]
        for name, path in (("RAG", c.rag), ("Full text", c.full)):
            if path.error:
                details.append(f"- **{name} failed:** {path.error}")
            else:
                details.append(
                    f"- {name}: {len(path.insights)} subjects kept, {path.dropped} dropped by the post-checks"
                )
        for name in ("match", "direction differs", "missed", "extra"):
            if groups[name]:
                details.append(f"- **{name.capitalize()}:** " + "; ".join(groups[name]))
        if c.seeded:
            details.append("- **Seeded views:** " + "; ".join(f"{s} ({d})" for s, d in sorted(c.seeded.items())))
        details.append("")
    return "\n".join(lines + [""] + details)


def compare(settings: Settings, only: str | None = None) -> list[ReportComparison]:
    with tempfile.TemporaryDirectory() as directory:
        session_factory = make_session_factory(f"sqlite:///{directory}/compare.db")
        llm = build_llm(settings, session_factory)
        index = ReportIndex(settings)
        index.vector_store = InMemoryVectorStore(get_embeddings(settings))
        index.reranker = Throttled(inner=get_reranker(settings))
        seed_research(session_factory, settings.seed_dir)
        reindex(session_factory, index)
        comparisons = []
        with session_factory() as db:
            reports = db.scalars(select(ReportRow).order_by(ReportRow.id)).all()
            for report in (r for r in reports if only in (None, r.id)):
                pages = list(
                    db.scalars(
                        select(ReportPageRow.text)
                        .where(ReportPageRow.report_id == report.id)
                        .order_by(ReportPageRow.page)
                    )
                )
                log.info("%s: RAG path", report.id)
                rag, sent = run_rag(llm, index, report.id, pages)
                log.info("%s: full-text path", report.id)
                full = run_full_text(llm, pages)
                seeded = {label.subject: label.direction for label in LABELS if label.report_id == report.id}
                total = len(index.vector_store.similarity_search("x", k=10_000, filter=index.report_filter(report.id)))
                comparisons.append(
                    ReportComparison(report.id, report.title, len(pages), rag, full, seeded, sent, total)
                )
    return comparisons


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", help="compare one Report (its id) instead of every seeded Report")
    parser.add_argument("--out", type=Path, default=OUT, help=f"where to write the Markdown report (default {OUT})")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    settings = Settings(vector_store="memory")
    report = render(settings, compare(settings, args.report))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report + "\n")
    log.info("Wrote %s", args.out)


if __name__ == "__main__":
    main()
