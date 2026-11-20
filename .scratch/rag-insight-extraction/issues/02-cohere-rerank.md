Status: ready-for-agent
Blocked by: 01

# Cohere cross-encoder reranking

## What to build
- `uv add langchain-cohere`. Check that the `cohere<6` pin resolves.
- Wrap each per-query retriever in `ContextualCompressionRetriever(base_compressor=CohereRerank(model=APP_RERANK_MODEL, top_n=APP_RERANK_TOP_N, client=<cohere.ClientV2, retries off>))`. Defaults: `rerank-v3.5` and `top_n` 4.
- Retrieval Provenance gains the rerank score, rank and rerank model for each kept Chunk, alongside the pre-rerank candidates.
- Add `APP_COHERE_API_KEY` to settings. A missing key is a clear startup or config error when the backend is live.
- **Tests:** a scripted fake `BaseDocumentCompressor` injected in place of `CohereRerank`. Add one test proving a rerank failure fails the extraction.

## Acceptance criteria
- [ ] One commit for this ticket
- [ ] APIs checked via Context7 (`langchain_classic` import path for `ContextualCompressionRetriever`)
- [ ] One rerank request per query, with no SDK retries. Verify on the wire or with a mocked transport
- [ ] The provenance shows candidate and reranked sets with scores
- [ ] The suite is green, offline
