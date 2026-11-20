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
- [x] APIs checked via Context7. Any deviation is recorded in ADR-0012
- [x] Spec risks 1–4 checked, with findings noted at the bottom of this file
- [x] Uploading a Markdown and a DOCX fixture produces Chunks in SQLite and the vector store, and pending Insights that cite real `chunk_id`s with a derived `page`
- [x] Exactly one LLM Exchange per extraction. The `insight_extracted` payload carries Retrieval Provenance
- [x] Fabricated chunk ids, or passages not in the Chunk, are dropped with reasons
- [x] A retrieval failure produces `extraction_status="failed"` and a failed event
- [ ] One commit for this ticket
- [x] Old events still verify, and the full suite is green, offline

## Findings (spec risks 1–4)

1. **`dl_meta` and pages.** Chunk page is `chunk.meta.doc_items[*].prov[*].page_no` and headings are `chunk.meta.headings`. But Markdown and DOCX carry **no** page provenance (`doc.pages == {}`, every `prov == []`), so they are one page (page 1; page text is the whole document's Markdown). PDF/PPTX are paginated and `export_to_markdown(page_no=n)` gives the page text. A first PDF conversion took ~38 s (model download); with the real models, per-page Markdown and chunk pages line up exactly (checked on a two-page PDF). Docling joins a paragraph that has no closing punctuation to the next page's text, so a Chunk can span pages and is cited by its first page. Images (PNG, JPEG) go through Docling's image pipeline with the same OCR, and are one page. Details in ADR-0012.
2. **Cohere pin.** `uv pip install --dry-run langchain-cohere` resolves (`langchain-cohere 0.6.0`, `cohere 5.21.1`) alongside the current `langchain`/`langchain-openai`/`langgraph`. Not added yet (ticket 02).
3. **Retriever callbacks.** A retriever invoked inside a LangGraph node with the node's config (`get_config()`) fires `on_retriever_start`/`on_retriever_end` on the same callback list as `ExchangeCapture`; `RetrievalProvenance` recorded all 14 queries in the tests.
4. **Install size and first run.** `.venv` is 1.6 GB (Docling brings PyTorch). Tests need no model download: Markdown/DOCX use Docling's SimplePipeline. They also pass with `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and the tiktoken cache disabled. This caught a real leak: `tiktoken.encoding_for_model` loads (downloads) the encoding, now `encoding_name_for_model`. In production the first chunking fetches the tiktoken encoding, so setup should pre-fetch it (ticket 08).

Models downloaded locally with `docling-tools models download layout tableformer rapidocr` (about 680 MB in `~/.cache/docling`; the RapidOCR weights come from ModelScope and timed out once, a retry worked) and the tiktoken `cl100k_base` encoding. The opt-in tests (`DOCLING_MODELS=1`: PDF and image) pass against them.
