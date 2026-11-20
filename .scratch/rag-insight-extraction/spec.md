Status: ready-for-agent

# RAG Insight extraction: Docling → Report Index → retrieve → rerank → generate

The terms follow `GLOSSARY.md`. This spec adds **Chunk**, **Report Index**, **Retrieval Query** and **Retrieval Provenance**. The decision is `docs/adr/0012-insight-extraction-is-standard-rag-over-a-report-index.md`. The background findings and API details are in `research.md`, next to this file.

**Builds on the merged LLM layer (ADR-0011, `origin/development` `57037fe`):**
- `get_chat_model(settings)` (`app/chat_model.py`)
- the shared pipeline graph `PIPELINE` with its `generate` node (`app/llm_graph.py`)
- `ModelLlm.complete` / `exchange_capture` and the `ExchangeCapture` callback (`app/exchanges.py`)
- the `pipeline_chat_model` fixture and fakes in `tests/fake_chat.py` / `tests/conftest.py`

**Standard patterns only.** Use what LangChain, LangGraph and Docling natively support and document, and nothing unusual:
- `DoclingLoader` + `HybridChunker`
- `VectorStore` / `as_retriever`
- `ContextualCompressionRetriever` + `CohereRerank`
- `with_structured_output`
- retriever callbacks
- `DeterministicFakeEmbedding` / `InMemoryVectorStore` in tests

Before coding, every ticket checks the APIs it touches against current docs via the Context7 MCP (LangChain, LangGraph, Docling, Chroma, Qdrant, Cohere). Where requirements conflict, the documented common practice wins. Any deliberate deviation is written into ADR-0012 with its reason. ADRs are not binding: amend whichever one gets in the way.

## Problem

Insight extraction (`app/reports.py::ingest`) reads a PDF page by page with pypdf: no OCR, no tables, no layout. It sends every page in one prompt, capped at `MAX_CHARS`. This drops tabular and scanned content, can't take larger or richer documents, and doesn't demonstrate a RAG pattern.

## Solution

### Ingest
- Uploads accepted: PDF, DOCX, PPTX, MD and TXT, up to about 50 pages or 20 MB. These replace `MAX_CHARS`.
- `POST /api/reports` stores the Report with `extraction_status="pending"`, records `report_ingested`, and schedules extraction as a FastAPI `BackgroundTasks` job. The UI polls until the status is `complete` or `failed`.
- `DoclingLoader(export_type=DOC_CHUNKS, chunker=HybridChunker(...))` does the conversion, with these settings:
  - tables on (ACCURATE mode);
  - OCR on;
  - picture description off;
  - HybridChunker tokenizer aligned to the embedding model (tiktoken), `max_tokens≈512`, `merge_peers=True`;
  - tables serialised as Markdown.
- Each Chunk gets a uuid5 id (`report_id` + chunk index) and flat metadata: `report_id`, `chunk_index`, `page`, and `headings` as a joined string. Docling's nested `dl_meta` is flattened, because Chroma accepts only flat metadata.
- The page texts shown in Insight Review come from the same Docling conversion (Markdown per page). They replace pypdf.

### Report Index
- A `report_chunk` SQLite table holds each Chunk's id, report_id, index, page, headings and text. It is created by a hand-written migration (ADR-0008) and is the record of truth.
- `get_vector_store(settings)` is the only place that knows the backend. It reads `APP_VECTOR_STORE` and returns:
  - `chroma`: `langchain-chroma`, embedded on disk at `APP_CHROMA_DIR`, one collection, cosine distance;
  - `qdrant`: `langchain-qdrant`;
  - `memory`: `InMemoryVectorStore`, for tests.

  `report_filter(report_id)` returns the backend's own filter syntax.
- Embeddings: `OpenAIEmbeddings(model=APP_EMBEDDING_MODEL, base_url=<OpenRouter>, check_embedding_ctx_length=False)`. The default model is `openai/text-embedding-3-small`.

### The LLM Graph
- **Retrieve.** The 14 Retrieval Queries, one per taxonomy subject from `GICS_SECTORS`/`ASSET_CLASSES`, are templated in `prompts.py` with a version.
  - Each runs a retriever over the Report (`k=APP_RETRIEVAL_K`, default 10, filtered by `report_filter`).
  - That retriever is wrapped in `ContextualCompressionRetriever(base_compressor=CohereRerank(model=APP_RERANK_MODEL, top_n=APP_RERANK_TOP_N))`. The defaults are `rerank-v3.5` and `top_n` 4.
  - The Cohere client is a `cohere.ClientV2`, built explicitly with SDK retries off.
- **Generate.** The de-duplicated union of reranked Chunks, each labelled with its `chunk_id`, goes to one structured-output call. Reuse `app.llm_graph.generate` (native `with_structured_output(method="json_schema")`) so `ExchangeCapture` records exactly one Exchange, as for every other pipeline step.
- **Graph shape.** ADR-0011 puts the four pipeline steps behind one `PIPELINE` graph reached through `LlmClient.complete`. Insight extraction gets its own compiled `StateGraph`, `extraction`, with the nodes `retrieve → rerank → generate`. That is LangGraph's documented RAG shape. It runs through a `ModelLlm` entry point that reuses `exchange_capture`, so the capture and metadata stay the same. Amend ADR-0011 to say this step now has its own graph.
- **Output.** `ExtractedInsight` gains `chunk_id` and keeps `passage`. Code fills `page` from the Chunk. The model no longer chooses the page.
- **Post-checks:**
  - the subject is in the taxonomy;
  - `chunk_id` is one of the Chunks that were sent;
  - the passage appears verbatim in that Chunk's text.

  Failures go into `dropped` with a reason, as today.
- **Retrieval Provenance** is collected with LangChain's retriever callbacks (`on_retriever_start`/`on_retriever_end`) and written into the `insight_extracted` payload:
  - query version and each query;
  - the retrieved and reranked chunk ids, pages and relevance scores, with their ranks;
  - the embedding model, rerank model and chunker config.
- **Failures.** Any embedding, vector-store, rerank or LLM failure marks the Report `extraction_status="failed"` and writes `insight_extracted` with outcome `failed` and the error. There is no retry and no full-text fallback.

### UI
- The upload dialog accepts the new types and limits.
- The Report shows pending / complete / failed and polls while pending.
- Insight Review shows each Insight's Chunk section heading next to its page.
- Retrieval Provenance appears in the existing Audit Event view. There is no new retrieval panel in v1.

### Existing Reports
- Existing Reports and Insights stay as they are.
- `scripts/reindex_reports.py` builds the Report Index for existing Reports. Because their pages came from pypdf, it chunks the stored page texts with Docling's Markdown path. It doesn't re-extract Insights.

### Evaluation
- A labelled set lives in `tests/fixtures/retrieval_eval.py`: for each seeded Report, subject → the Chunk(s) expected to hold the view.
- A pytest eval reports hit-rate@k and MRR, offline with deterministic fakes, and also runs live through an opt-in marker.
- `scripts/compare_extraction.py` is run once: for each seeded Report it compares the Insights from RAG and from the old full-text prompt.
- `scripts/eval_ragas.py` is an optional RAGAS run, with `ragas` as an optional dependency group. Its judge model comes from `get_chat_model("eval")`. Its calls are not Exchanges and are not audited, and it writes a report file only.

### Config
These settings are added to `.env.example` and the README:
- `APP_VECTOR_STORE` (default `chroma`)
- `APP_CHROMA_DIR`
- `APP_EMBEDDING_MODEL`
- `APP_RERANK_MODEL`
- `APP_RETRIEVAL_K`
- `APP_RERANK_TOP_N`
- `APP_COHERE_API_KEY`

Setup pre-fetches the Docling models (`docling-tools models download`).

### Tests
Tests stay offline, with no network access and no model downloads. They use:
- `DeterministicFakeEmbedding`
- `InMemoryVectorStore`
- a scripted fake `BaseDocumentCompressor` in place of `CohereRerank`
- the LLM layer's fake chat model
- Markdown/DOCX fixture files

## Out of scope
- Picture or figure description (VLM)
- LLM-generated queries
- Hybrid/BM25 search
- A retrieval panel in the UI
- Re-extracting existing Insights
- Running Qdrant in production (the adapter and contract tests are in scope; running it isn't)

## Risks to check early (ticket 01)
1. `DoclingLoader` chunk metadata: confirm the page and headings paths in `dl_meta`, and that the per-page Markdown export lines up with the Chunk pages.
2. `CohereRerank` pins `cohere<6`. Check that it resolves alongside `langchain>=1.5.2` and `langchain-openai>=1.8.3`, which are already in `pyproject.toml`.
3. Retriever callbacks fire inside a LangGraph node with `config` passed through, and show up in the same callback handler as `ExchangeCapture`.
4. Install size and first-run time with Docling. Confirm that tests never trigger a model download.
