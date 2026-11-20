Status: done
Blocked by: 02

# Retrieval eval (hit-rate@k, MRR) and one-off comparison with full-text extraction

## What to build
- `tests/fixtures/retrieval_eval.py`: for each seeded Report, subject → the Chunk ids (or page and passage) expected to hold the view.
- A pytest eval computing hit-rate@k and MRR before and after rerank. It runs offline with deterministic fakes as a smoke test, and live behind an opt-in marker (e.g. `-m live_eval`) with thresholds.
- `scripts/compare_extraction.py` runs the RAG path and the old full-text prompt on each seeded Report. It reports which Insights match, which are missed and which are extra, and writes a Markdown report under `.scratch/rag-insight-extraction/`.

## Acceptance criteria
- [x] One commit for this ticket
- [x] The offline eval runs in the normal suite. The live eval is skipped unless opted in
- [x] A comparison report is produced, with findings summarised at the bottom of this file and the k/top_n defaults tuned if needed

## Findings (run 2026-11-20, live: `openai/text-embedding-3-small`, `rerank-v3.5`, `anthropic/claude-sonnet-5.5`)

Full report: `.scratch/rag-insight-extraction/comparison.md` (`uv run python -m scripts.compare_extraction`). The live eval is `uv run pytest tests/test_retrieval_eval.py -m live_eval`.

**Retrieval (19 seeded, human-verified views over the 5 seeded Reports).**

| | hit-rate | MRR |
| --- | --- | --- |
| Vector store, top k=10 | 1.000 | 0.929 |
| After rerank, top_n=4 | 1.000 | 0.974 |

Every view's Chunk was in the set sent to the model (1.000), and the reranker moved it nearer rank 1 (MRR 0.929 → 0.974). The live thresholds in `tests/fixtures/retrieval_eval.py` sit just under these values.

**RAG vs full text (one run per Report, so model variance is not measured).**
- The three synthetic house views (2 short pages each) and the UBS Yearbook summary (24 pages): both paths gave the same Insights with the same directions. No misses, no extras, no direction differences.
- Fidelity Q2 (19 pages): 7 Insights match; RAG **missed Health Care (neutral) and Real Estate (positive)**, which full text found. Neither path found Communication Services or Financials, two seeded views, so the seeded recall is 7/11 for RAG and 9/11 for full text. RAG added nothing the full-text path did not find.
- The two RAG misses were not retrieval misses: both views' Chunks were in the eval's sent set (sent-recall 1.000). The model had the text and did not report the views. The likely cause is generation over a large table chunk, which this run does not prove.
- RAG sent 59% (Fidelity, 13 of 26 Chunks) and 45% (UBS, 16 of 41 Chunks) of the text the full-text path sent. On the 2-page views it is the same text, as k covers every Chunk.

**Defaults.** `APP_RETRIEVAL_K=10` and `APP_RERANK_TOP_N=4` stay. Recall is at the ceiling, so this label set cannot tell a better setting from the current one, and the misses are on the generation side. The eval's labels are easy (short, explicit sentences); a harder set would be needed to tune further.

**Follow-ups.**
- Ticket 07 (RAGAS) or a larger label set can look at the Fidelity generation misses (e.g. ask the model per table row, or send the whole scorecard Chunk first).
- A Cohere **Trial key allows 10 calls a minute**, and an extraction makes 14 rerank calls, so on a Trial key a live extraction fails with a 429 (no SDK retries, by design). The evals throttle their reranker (`RERANK_INTERVAL_SECONDS`, default 6.5; 0 for a Production key). Ticket 08's setup docs should say a Production key is needed.
