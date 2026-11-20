---
status: accepted
supersedes: ADR-0007 (its rejection of RAG)
amends: ADR-0004 (retrieval provenance on the Audit Event; embedding and rerank calls are not Exchanges), ADR-0011 (Insight extraction gets its own LLM Graph)
---

# Insight extraction is a standard LangChain RAG pipeline over a Report Index

Insight extraction no longer sends every page of a Report in one prompt. It follows the standard LangChain/LangGraph RAG pattern, using natively supported components and no custom orchestration:

- **Load and chunk.** `DoclingLoader(export_type=DOC_CHUNKS, chunker=HybridChunker(...))` converts the upload. Tables are extracted (ACCURATE mode) and OCR is on. Picture description is off: Docling's own vision-model call would bypass Exchange capture.
  - Each Chunk gets a uuid5 id and flat metadata: `report_id`, `page` and `headings`.
  - The page texts shown to the reviewer come from the same Docling conversion.
- **Index.** Every Chunk is written to SQLite, the record of truth, and embedded into a vector store. The two together are the Report Index.
  - The vector store is built by one app-owned factory, `get_vector_store()`, and filtered through `report_filter(report_id)`. These are the only places that know the backend: Chroma first, Qdrant later.
  - Chroma is embedded on disk, with one collection, cosine distance and `report_id` filtering.
- **Ingest is a background task.** `POST /api/reports` checks the upload (type, bytes, size, PDF page count), stores the Report as `pending`, records `report_ingested` and returns. FastAPI `BackgroundTasks` then runs `extraction.process` with its own DB session (the request's closes with the response): Docling, indexing, retrieval and the one LLM call, ending `complete` or `failed`. `insight_extracted` carries the page and Chunk counts, which are unknown at upload. The Report screens poll while a Report is pending.
- **Retrieve, rerank, generate**, as Insight extraction's own LLM Graph (`extraction`), alongside ADR-0011's shared `PIPELINE`. The `generate` node and `ExchangeCapture` are reused unchanged:
  - **Retrieve:** one fixed Retrieval Query per taxonomy subject, written in `prompts.py` and versioned. Each query takes `k` Chunks from the Report.
  - **Rerank:** Cohere's cross-encoder (`CohereRerank` via `ContextualCompressionRetriever`) keeps `top_n` per query.
  - **Generate:** one structured-output call through `get_chat_model()` over the de-duplicated union of Chunks. The model cites `chunk_id` and quotes a passage. Code derives `page` from the Chunk.
- **Embeddings** go through OpenRouter's OpenAI-compatible endpoint (`OpenAIEmbeddings`). **Reranking** calls Cohere directly with SDK retries off. Both models come from config.

## Answers to ADR-0007's objections

- **"Reports fit in one prompt."** That is still often true. RAG is adopted for precision, for multimodal extraction (tables, OCR, DOCX/PPTX), for larger Reports, and because the demonstrator should show a standard RAG pattern. It is not a size necessity.
- **"The embedding model and index are not versioned."** Every `insight_extracted` event records Retrieval Provenance:
  - the Retrieval Query version and each query;
  - the retrieved and reranked chunk ids, pages and scores, with their ranks;
  - the embedding and rerank models;
  - the chunker config.
- **"Similarity retrieval is hard to show an Auditor."** Chunk text lives in SQLite, so every cited and retrieved Chunk can be shown verbatim, and the vector index can be rebuilt from it. Retrieval is captured through LangChain's own retriever callbacks, not a hand-written hook.
- **"A passage could be retrieved without human approval."** RAG only changes how Insights are *proposed*. Every Insight still starts pending, and only an approved Insight can inform a Research Tilt.

## Considered Options

- **Keep the full-text single prompt**: rejected. It has no table or OCR handling, it is capped by prompt size, and it doesn't demonstrate RAG.
- **LLM-generated queries (`MultiQueryRetriever`)**: rejected for v1. It adds a model call and makes the queries different on every run. Fixed per-subject queries give the same queries every time and can be audited.
- **One generate call per subject**: rejected. It costs 14 Exchanges per Report. One "stuff" call keeps the step at one model request.
- **Reranking via OpenRouter `/rerank`**: rejected. It would need a hand-written compressor, and `CohereRerank` is the documented LangChain path.
- **Capturing embedding and rerank calls as LLM Exchanges**: rejected. They are not chat calls. Their inputs, models and outputs are recorded as Retrieval Provenance on the Audit Event instead.

## Consequences

- **Exchanges:** the step is still one LLM Exchange, and its Audit Event Trajectory is a list of one.
- **Failures:** a failure in embedding, the vector store or reranking is handled like an LLM failure today. The Report is marked `failed` and an `insight_extracted` event records the error. There is no retry and no fallback to full text.
- **Recall risk:** retrieval can miss a view that the full text would have shown. A pytest retrieval eval (hit-rate@k, MRR) and a one-off comparison against the full-text path measure this. RAGAS is an optional offline script whose judge calls are not audited.
- **Install weight:** Docling brings PyTorch and model downloads, so setup pre-fetches the models. Tests use Markdown/DOCX fixtures, fake embeddings, `InMemoryVectorStore` and a fake reranker, so they need no network access and no model downloads.
- **Existing Reports:** existing Reports and Insights stay as they were extracted. A script re-indexes them.
- **Second key:** `APP_COHERE_API_KEY` is added alongside the OpenRouter key.

## Implementation notes (ticket 01, checked against Context7 and the installed packages)

Deviations from the plan above, each with its reason:

- **Page-less formats are one page.** Docling gives Markdown and DOCX no page provenance (`DoclingDocument.pages` is empty and every item's `prov` is empty). Their Chunks cite page 1 and their page text is the whole document's Markdown. Only PDF and PPTX are paginated. Plain text goes through Docling's Markdown reader, so the old form-feed page breaks of `.txt` uploads no longer make pages (a form feed is read as a paragraph break). Seeded Reports keep their pypdf pages until they are re-indexed (ticket 05).
- **Page texts from the same conversion** are taken by passing the loader a recording wrapper as its `converter` (the documented `ConversionBackend` seam), which keeps the `DoclingDocument` for `export_to_markdown(page_no=n)`. `DoclingLoader` itself does not expose the document.
- **Flat metadata** comes from a custom `BaseMetaExtractor` (`page`, `headings` joined by `" > "`), as the loader's default nests `dl_meta`.
- **Tables as Markdown** needs a `serializer_provider` on `HybridChunker` (`MarkdownTableSerializer`): Docling's default chunk serialisation is triplet notation.
- **The Chunk text** stored and embedded is the chunker's contextualised text (section headings, then the body), as Docling recommends for embedding. The passage check is a normalised substring test against it.
- **The tokenizer** is `tiktoken` (via Docling's `OpenAITokenizer`), which fetches its encoding on first use. `chunk_tokenizer` is the one seam, and tests replace it with a word counter; `encoding_name_for_model` is used where only the name is needed, because loading the encoding would hit the network.
- **Retrieval Provenance before reranking** records chunk ids, pages and ranks only: a vector retriever returns no score. `relevance_score` is recorded when a Document carries one, which is what `CohereRerank` adds (ticket 02). With reranking, each Retrieval Query records its `candidates` (the vector store's `k`, in order) and its `retrieved` Chunks (the reranker's `top_n`, with `relevance_score` and rank). The vector retriever runs as a child of `ContextualCompressionRetriever`, so the callback tells the two apart by parent run.
- **Embeddings** are the second provider seam: `app/report_index.py` imports `langchain_openai` for `OpenAIEmbeddings`, alongside `chat_model.py`.
- **`report_chunk`** is the table name the spec uses, and it is created with the other tables. The only migration is the nullable `insights.chunk_id` column (`_add_insight_chunk_id`).
- **Docling's PDF pipeline** downloads its layout and table models on first use (about 38 s for a two-page PDF here); the Markdown and DOCX pipelines download nothing.
- **`memory` backend and `ReportIndex`.** `get_vector_store` and `report_filter` stay the only functions that branch on the backend (`chroma` and `memory` so far). `ReportIndex` is a thin holder the app keeps in `app.state`: it builds the store on first use, so the app starts without an embedding key, and a test sets the store. It adds no backend knowledge of its own. The settings `APP_VECTOR_STORE`, `APP_CHROMA_DIR`, `APP_EMBEDDING_MODEL` and `APP_RETRIEVAL_K` are added now; `APP_COHERE_API_KEY`, `APP_RERANK_MODEL` (`rerank-v3.5`) and `APP_RERANK_TOP_N` (4) arrived with ticket 02.
- **Images.** PNG and JPEG uploads go through Docling's image pipeline with the same OCR and table options as a PDF page, and are one page. OCR is RapidOCR (Docling's auto choice here), so the OCR weights are part of the models setup pre-fetches. Small text can be misread: the Insight's passage check holds the model to what OCR actually produced, so a misread quote is dropped, not repaired.
- **Reranking (ticket 02).** `ContextualCompressionRetriever` is imported from `langchain_classic.retrievers` (`langchain-classic`), where LangChain 1.x keeps it. The Cohere SDK retries twice by default and `CohereRerank` offers no way to turn that off, so `NoRetryClientV2` (a `cohere.ClientV2` that sends `max_retries=0`) is passed as `client`. A missing `APP_COHERE_API_KEY` stops the app at startup when `APP_LLM_API_KEY` is set (the backend is live), and fails the extraction otherwise.
