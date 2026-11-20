Status: ready-for-agent
Blocked by: none

# Tracer: Docling → Report Index → retrieve → one generate call, end to end

Spec: `../spec.md`. ADR: `docs/adr/0012-*`. API notes: `../research.md`.

## What to build
This is the thinnest end-to-end slice with **no reranker yet**. Ingest stays synchronous for now (ticket 03 moves it to the background).
- **Deps:** `uv add docling langchain-docling langchain-chroma`. `langchain-openai` is already present, for embeddings. Check the versions against Context7 and PyPI.
- **Load and chunk:** `DoclingLoader(export_type=DOC_CHUNKS, chunker=HybridChunker(tokenizer aligned to the embedding model, max_tokens≈512, merge_peers=True))`, with tables on and OCR on.
  - Flatten `dl_meta` into `report_id`, `chunk_index`, `page` and `headings`.
  - Chunk ids are uuid5.
  - The page texts in Insight Review come from the same Docling conversion.
- **Storage:** a `report_chunk` SQLite table, with a hand-written migration.
- **Vector store:** `get_vector_store(settings)` for `chroma` (on disk, cosine) and `memory` (`InMemoryVectorStore`), plus `report_filter(report_id)`.
- **Embeddings:** `OpenAIEmbeddings` via OpenRouter, model from `APP_EMBEDDING_MODEL`.
- **Retrieval Queries:** 14, versioned in `prompts.py`.
- **LLM Graph:** a new compiled `extraction` `StateGraph` (see spec, "Graph shape"): a `retrieve` node (k from `APP_RETRIEVAL_K`) → a `generate` node reusing `app.llm_graph.generate`. Run it through a `ModelLlm` entry point that reuses `exchange_capture`, and amend ADR-0011.
  - Prompt version `insight_extraction@v2`.
  - `ExtractedInsight` gains `chunk_id`, and code derives `page`.
- **Post-checks:** taxonomy; `chunk_id` was one of the Chunks sent; the passage is verbatim in the Chunk.
- **Retrieval Provenance:** collected via retriever callbacks and written into the `insight_extracted` payload.
- **Failures:** a failure anywhere in retrieval is handled like today's LLM failure.
- **Tests:** offline, using `DeterministicFakeEmbedding`, `InMemoryVectorStore`, the `pipeline_chat_model` fixture or `tests/fake_chat.py` fakes, and a Markdown/DOCX fixture. Update `tests/test_research.py`.

## Acceptance criteria
- [ ] APIs checked via Context7. Any deviation is recorded in ADR-0012
- [ ] Spec risks 1–4 checked, with findings noted at the bottom of this file
- [ ] Uploading a Markdown and a DOCX fixture produces Chunks in SQLite and the vector store, and pending Insights that cite real `chunk_id`s with a derived `page`
- [ ] Exactly one LLM Exchange per extraction. The `insight_extracted` payload carries Retrieval Provenance
- [ ] Fabricated chunk ids, or passages not in the Chunk, are dropped with reasons
- [ ] A retrieval failure produces `extraction_status="failed"` and a failed event
- [ ] One commit for this ticket
- [ ] Old events still verify, and the full suite is green, offline
