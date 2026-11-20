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
