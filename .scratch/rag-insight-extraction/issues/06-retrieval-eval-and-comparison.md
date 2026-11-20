Status: ready-for-agent
Blocked by: 02

# Retrieval eval (hit-rate@k, MRR) and one-off comparison with full-text extraction

## What to build
- `tests/fixtures/retrieval_eval.py`: for each seeded Report, subject → the Chunk ids (or page and passage) expected to hold the view.
- A pytest eval computing hit-rate@k and MRR before and after rerank. It runs offline with deterministic fakes as a smoke test, and live behind an opt-in marker (e.g. `-m live_eval`) with thresholds.
- `scripts/compare_extraction.py` runs the RAG path and the old full-text prompt on each seeded Report. It reports which Insights match, which are missed and which are extra, and writes a Markdown report under `.scratch/rag-insight-extraction/`.

## Acceptance criteria
- [ ] One commit for this ticket
- [ ] The offline eval runs in the normal suite. The live eval is skipped unless opted in
- [ ] A comparison report is produced, with findings summarised at the bottom of this file and the k/top_n defaults tuned if needed
