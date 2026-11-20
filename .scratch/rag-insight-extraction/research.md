# Research: RAG pipeline for Insight extraction

Researched 2026-11-19 for the planned refactor on branch `feature/rag-insight-extraction`. Vocabulary follows `GLOSSARY.md`. Package versions come from PyPI on that date. Every claim cites a URL or Context7 library ID. Anything not checked against a primary source is marked **UNVERIFIED**.

## Summary

1. **An ADR is needed first.** ADR-0007 rejects "Retrieval over a vector store (RAG)" in so many words. Its reasons: Reports fit in one prompt; the embedding model and index are not versioned; similarity retrieval is hard to show an Auditor. ADR-0011 drops only 0007's single-call/no-LangGraph stance. A new ADR (0012) has to answer each of those three reasons (`docs/adr/0007-llm-steps-are-single-schema-bound-calls.md`).
2. **The graph is `ingest` → `retrieve` → `rerank` → `generate`, as a fixed `StateGraph` with no agent loop.** The query set is deterministic: one query per taxonomy subject (11 GICS sectors and 3 Asset Classes). Retrieval is filtered to the one Report. `generate` makes **one** structured-output call over the union of reranked chunks, so the step stays a Trajectory of one Exchange.
3. **Use Docling `DocumentConverter` → `HybridChunker` directly.** The tokenizer is aligned to the embedding model, tables are serialised as Markdown, and `contextualize()` text goes into the embeddings. `langchain-docling`'s `DoclingLoader(export_type=DOC_CHUNKS)` is the documented LangChain wrapper around exactly this, but it emits nested `dl_meta`, which Chroma rejects. Either flatten it with a custom `meta_extractor`, or skip the loader and build `Document`s yourself. Recommendation: use the loader with a custom `MetaExtractor`.
4. **Docling text replaces pypdf text everywhere.** `ReportPageRow` pages must come from the same `DoclingDocument`. Otherwise the deterministic `passage_on_page` check compares against different text than the model saw.
5. **Chunking default:** `HybridChunker(max_tokens≈512, merge_peers=True)` plus `MarkdownTableSerializer`. Avoid sizing chunks to the embedding model's maximum (e.g. 8191 tokens): large chunks dilute retrieval and give the reranker fewer, coarser candidates. Semantic chunking and parent-document retrieval were considered and are not recommended for v1 (see §3).
6. **Embeddings: OpenRouter does serve them** (`POST /api/v1/embeddings`, 38 models listed). Use `OpenAIEmbeddings(base_url=OpenRouter, model="openai/text-embedding-3-small", check_embedding_ctx_length=False)`. That keeps one provider key and one gateway. Build it in a new `get_embeddings()` beside `get_chat_model` in `app/chat_model.py`.
7. **Reranking: OpenRouter also serves Cohere rerank** (`POST /api/v1/rerank`, `cohere/rerank-v3.5`, `cohere/rerank-4-*`, `cohere/rerank-5-*`). `langchain-cohere`'s `CohereRerank` talks only to Cohere's own SDK client (`cohere.ClientV2`). Decision for the user: Cohere direct via `CohereRerank` (the documented LangChain path; needs `APP_COHERE_API_KEY`), or a small `BaseDocumentCompressor` over OpenRouter's rerank (one key, but hand-rolled). Default: `CohereRerank` with `rerank-v3.5`. It is the model OpenRouter's own cookbook uses.
8. **`langchain-cohere` 0.6.0 pins `cohere<6.0`**, while the current Cohere SDK is 7.3.2. Expect an older SDK in the lockfile.
9. **Vector store seam:** LangChain's `VectorStore` / `as_retriever()` is a sufficient seam for add, search and delete by ID. It is **not** sufficient for three things: metadata-filter syntax (Chroma takes a `where` dict; Qdrant takes `models.Filter`; `InMemoryVectorStore` takes a Python callable), collection/distance configuration, and score semantics (Chroma returns a distance by default). Put those behind one small app-owned function (`report_filter(report_id)`, plus `build_vector_store(settings)`).
10. **IDs:** give each chunk a deterministic **UUID** (`uuid5` of report id + chunk index). Qdrant accepts only unsigned ints or UUIDs. Chroma and InMemory accept any string. A uuid5 makes re-ingestion idempotent and lets an Audit Event cite chunks stably.
11. **Distance:** set cosine explicitly on both stores: Chroma `collection_configuration={"hnsw": {"space": "cosine"}}`, and Qdrant `Distance.COSINE`, which is already the default.
12. **Audit provenance:** a LangChain callback's `on_retriever_start` / `on_retriever_end` sees the query and returned `Document`s, including `relevance_score` after `CohereRerank`. Record a **retrieval record** (query, chunk ids, pages, vector score, rerank score, rank, embedding model, rerank model, chunker config, index version) and anchor it in the `insight_extracted` Audit Event next to the Exchange ref. Embedding and rerank calls are not chat-model calls, so `ExchangeCapture` never sees them; that is correct, since an Exchange is one chat-model call.
13. **Offline tests:** `DeterministicFakeEmbedding(size=…)` + `InMemoryVectorStore` + a fake `BaseDocumentCompressor` (the order is the test's script) + the existing `FakeChatModel`. Docling's PDF pipeline downloads layout/table models on first use. Tests should use Markdown/DOCX input (SimplePipeline, no model download), or a committed `DoclingDocument` JSON fixture.
14. **Evaluation:** a small labelled set (Report, subject → gold chunk ids), with hit-rate@k and MRR computed in plain pytest. RAGAS 0.4.4 is optional, run as a live script only. It pulls `langchain-community`, `datasets` and `instructor`, so keep it out of the main dependency group.

## Current Insight extraction (as found in code)

Note on the worktree: this branch already has the LangGraph layer's code (`app/llm_graph.py`, `app/chat_model.py`, the `ExchangeCapture` callback in `app/exchanges.py`). It does **not** have `docs/adr/0011-…` or the LangChain dependencies in `pyproject.toml`, which still lists `pydantic-ai-slim` and `pypdf` only. Those changes exist uncommitted in the main checkout (`/Users/aniruddh/git/alpha-portfolio-ai`). Rebase onto the finished LangGraph work before starting.

- **Entry point:** `POST /api/reports` (`app/routers/reports.py:85-113`) needs the `report:upload` permission (Research Analyst). It reads the upload and runs `reports.ingest(db, llm, title, filename, content, uploader)` in a thread pool.
- **Inputs** (`app/reports.py:70-96`, `extract_pages`): a single uploaded file, either a PDF or a `.txt`/`.md` file.
  - A PDF is read with `pypdf.PdfReader(...).pages[i].extract_text()`, one string per page. Text files split on form feed (`\f`).
  - There is no OCR: "scanned PDFs are not supported". There are no tables, figures or layout.
  - The limit is `MAX_CHARS = 400_000`.
  - Pages are stored as `ReportPageRow(report_id, page, text)`, and the Report as `ReportRow` with `extraction_status`.
- **Prompt** (`app/prompts.py:18-36`): `INSIGHT_EXTRACTION` (`insight_extraction@v1`). The user message is **every page**, as `[Page N]\n<text>` (`extraction_request`, `app/reports.py:99-107`). There is no retrieval at all.
- **Output schema** (`app/reports.py:35-48`):
  ```python
  class ExtractedInsight(BaseModel):
      subject_kind: Literal["sector", "asset_class"]
      subject: str
      direction: Literal["positive", "neutral", "negative"]
      confidence: Literal["low", "medium", "high"]
      page: int
      passage: str  # verbatim quote from that page


  class Extraction(BaseModel):
      insights: list[ExtractedInsight]
  ```
- **How it is called:** `LlmClient.complete(LlmRequest(task, prompt_version, system, user, schema))`.
  - `ModelLlm.complete` (`app/exchanges.py:419-449`) runs the shared one-node `PIPELINE` graph (`app/llm_graph.py`: START → `generate` → END).
  - The node calls `model.with_structured_output(schema, method="json_schema", include_raw=True)`.
- **Deterministic checks after the call** (`app/reports.py:221-229`): the subject must be in the taxonomy (`GICS_SECTORS` / `equity|bond|cash`), the page must exist, and `passage_on_page` (normalised substring) must hold. Anything that fails is dropped and recorded with its reason. What is kept becomes `InsightRow(status="pending")`. Only an Insight approved through Insight Review is ever used (`approved_insights`).
- **Audit:**
  - `report_ingested` Audit Event (by the uploader).
  - Then `insight_extracted`, by `Actor.system("insight-extractor", model, prompt_version)` with parent `report_ingested`. The payload is `{outcome, insight_count, dropped, exchanges:[{exchange_id, exchange_hash}]}`.
  - The Exchange row is written by the `ExchangeCapture` callback (`app/exchanges.py:291-374`). It stores the messages sent, raw reply, usage, latency and Graph Node (`langgraph_node`).
  - Each `InsightRow.extract_event_id` points at the event. `insight_approved` / `insight_rejected` events have that event as parent.
  - Lineage reads this chain: Report passage → Insight → Research Tilt (`app/lineage.py`).
- **Tests:** `tests/test_research.py` covers pending cited Insights, PDF page references, off-event-loop ingestion, logging of model and prompt version, dropped Insights, failed extraction, rejected uploads, approved-only retrieval, roles, seeded Insights and a `LLM_LIVE=1` smoke test.

## 1. Docling: multimodal document extraction

Versions: `docling` 2.151.1, `docling-slim` 2.151.1, `docling-core` 2.107.1, `langchain-docling` 3.0.0 ([PyPI](https://pypi.org/project/docling/), [PyPI](https://pypi.org/project/langchain-docling/)).

- **Formats:** PDF, DOCX/XLSX/PPTX, Markdown, HTML, CSV, images and more (`/docling-project/docling`, docs/usage/supported_formats.md).
  - DOCX goes through `SimplePipeline`, which downloads no PDF models. Pipelines are built lazily per input format (docling/document_converter.py via `/docling-project/docling`).
  - This matters for tests: a Markdown or DOCX fixture converts without the layout and table models.
- **PDF options** (`PdfPipelineOptions`, docling/datamodel/pipeline_options.py via `/docling-project/docling`):
  - `do_table_structure=True` is the default.
  - `do_ocr=True` is the default. It "significantly increases processing time" and needs an installed engine. On macOS the logs show `ocrmac` auto-selected (`/docling-project/docling-langchain` notebook output).
  - The docstring recommends a `document_timeout` of about 90-120 s for production.
  - `TableStructureOptions(mode=TableFormerMode.ACCURATE)`.
  - `generate_picture_images=True, images_scale=2.0` keeps figure crops.
  - Picture description: `do_picture_description=True` with a local VLM (`smolvlm_picture_description`), or `PictureDescriptionApiOptions(url=…/v1/chat/completions, headers, params={"model":…}, prompt, timeout)`. The API option **requires `enable_remote_services=True`**, and Docling notes it "will send your data to the remote service provider" (docs/usage/enrichments.md, `/docling-project/docling`).
  - An OpenRouter VLM could be the remote endpoint. That model call would **bypass `ExchangeCapture`**, because Docling makes it, not LangChain. For the audit chain, leave picture description off in v1, or record it as a separate artefact. See Decisions.
- **Offline / air-gapped:** `docling-tools models download` pre-fetches the layout, tableformer, picture-classifier, code-formula and rapidocr models into `$HOME/.cache/docling/models`. Pass `PdfPipelineOptions(artifacts_path=…)` to use them (docs/usage/advanced_options.md, docs/reference/cli.md, `/docling-project/docling`).
- **From bytes** (the upload path): `converter.convert(DocumentStream(name="x.pdf", stream=BytesIO(content)))` (docs/usage/advanced_options.md).
- **Install weight:** `docling` = `docling-slim[standard]`, which brings PyTorch. The docs show a CPU-only Linux wheel index (`--extra-index-url https://download.pytorch.org/whl/cpu`) (docs/getting_started/installation.md). `langchain-docling` needs its `local` extra to run the converter in-process: `docling-slim[standard]` (PyPI requires_dist).
- **Provenance:** every `DocItem` has `prov: list[ProvenanceItem(page_no, bbox, charspan)]` (docling_core/types/doc/common/reference.py, `/docling-project/docling-core`). Chunks carry `meta.doc_items`, `meta.headings` and `meta.origin` (filename, mimetype, `binary_hash`) (hierarchical_chunker.py, `/docling-project/docling-core`). The pages a chunk touches are `sorted({p.page_no for it in chunk.meta.doc_items for p in it.prov})` (docs/examples/rag_topk.ipynb). `DoclingDocument.iterate_items(page_no=n)` yields only the items on page `n`, which is the way to rebuild `ReportPageRow` text from the same document (docling_core document.py).

```python
from io import BytesIO
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableStructureOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption

opts = PdfPipelineOptions(
    do_ocr=True,
    do_table_structure=True,
    table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
    document_timeout=120,
)
converter = DocumentConverter(format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)})
dl_doc = converter.convert(DocumentStream(name=filename, stream=BytesIO(content))).document
```

(Shape from `/docling-project/docling` examples. Passing `table_structure_options` and `document_timeout` as constructor kwargs is **UNVERIFIED**; the docs set them as attributes.)

## 2. Chunking

Docling chunking concepts (docs/concepts/chunking.md, `/docling-project/docling`):

- **`HierarchicalChunker`:** one chunk per document element (paragraph, list, table), with heading ancestry attached. There is no token limit.
- **`HybridChunker`:** starts from the hierarchical chunks. It splits only chunks that are oversized for the tokenizer, and merges undersized neighbours that share headings and captions (`merge_peers=True` by default). The tokenizer is "typically to be aligned to the embedding model tokenizer".
- **Tokenizers:** `HuggingFaceTokenizer.from_pretrained(model_name=…, max_tokens=…)`, or `OpenAITokenizer(tokenizer=tiktoken.get_encoding(...), max_tokens=…)`. The OpenAI one needs `docling-core[chunking-openai]` (docling_core/transforms/chunker/tokenizer/openai.py on GitHub; docs/concepts/chunking.md).
- **`contextualize(chunk)`** prepends headings and captions. It is the text to embed, and `DoclingLoader` uses it as `page_content` in DOC_CHUNKS mode (`/docling-project/docling-langchain` loader.md).
- **Tables:** the default serialisation is a triplet format. The docs show swapping in `MarkdownTableSerializer` through a `ChunkingSerializerProvider`, because "language models may perform better on complex tables" in Markdown (docs/examples/rag_opensearch.ipynb).

```python
import tiktoken
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer, ChunkingSerializerProvider
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer  # import path UNVERIFIED


class MDTables(ChunkingSerializerProvider):
    def get_serializer(self, doc):
        return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer())


chunker = HybridChunker(
    tokenizer=OpenAITokenizer(tokenizer=tiktoken.get_encoding("cl100k_base"), max_tokens=512),
    merge_peers=True,
    serializer_provider=MDTables(),
)
for i, chunk in enumerate(chunker.chunk(dl_doc)):
    text = chunker.contextualize(chunk)
    pages = sorted({p.page_no for it in chunk.meta.doc_items for p in it.prov})
```

Alternatives compared for financial research documents (house views, outlooks):

| Strategy | Source | Fit |
|---|---|---|
| `HybridChunker` (structure + token limit) | Docling docs | **Recommended.** Keeps a sector section with its heading, keeps tables whole, respects the embedding window, and gives page provenance for free. |
| `HierarchicalChunker` | Docling docs | Good structure, but no size bound: long sections can exceed the embedding window and tiny ones become noise. Use it only if sections are known to be short. |
| `RecursiveCharacterTextSplitter` (1000/200 chars) | LangChain knowledge-base tutorial (`/websites/langchain_oss_python_langchain`) | The LangChain default "for generic text". It ignores layout and tables and loses page provenance unless split per page. It is a baseline for evaluation only. |
| `SemanticChunker` (`langchain_experimental.text_splitter`, `langchain-experimental` 0.4.2) | GitHub langchain-experimental | Embedding-driven breakpoints. It costs an embedding call per sentence at ingest, is experimental, and is non-deterministic across embedding models. That makes it harder to audit. Not recommended. |
| Parent-document retrieval (`langchain_classic.retrievers.ParentDocumentRetriever`) | GitHub langchain (`langchain_classic`) | Retrieves small chunks and returns their parent section. Docling's `contextualize()` (headings in every chunk) already gives most of that benefit. It needs a docstore as well as the vector store, and `langchain_classic` is the legacy package. Revisit if eval shows small chunks miss context. |

**Size:** keep chunks well under the embedding model's window. Docling's own examples use 400 tokens (rag_topk) or the embedding model's max (rag_opensearch). Recommended default is **512 tokens**, to be tuned with the eval in §8. Chunks at the embedding model's maximum (8191 tokens for `text-embedding-3-*`) would each span a page or more, which defeats retrieval within a single Report (**UNVERIFIED** as a measured claim; this is reasoning, to be confirmed by eval).

## 3. LangChain loaders and the `Document` shape

`DoclingLoader(file_path, converter=None, convert_kwargs=None, export_type=ExportType.DOC_CHUNKS, chunker=HybridChunker(), meta_extractor=MetaExtractor())` (`/docling-project/docling-langchain`, _autodocs/api-reference/loader.md):
- `file_path` is a path or URL string, not bytes. Uploads would need a temp file, or a custom path. Whether it accepts a `DocumentStream` is **UNVERIFIED**.
- In DOC_CHUNKS mode, `page_content = chunker.contextualize(chunk)` and `metadata = {"source": file_path, "dl_meta": chunk.meta.export_json_dict()}`.
- `dl_meta` is **nested**. Chroma requires flat scalar metadata values: `langchain_chroma` re-raises "Expected metadata value to be…" with a hint to use `filter_complex_metadata` (langchain_chroma/vectorstores.py on GitHub). A custom `BaseMetaExtractor` should therefore emit flat keys: `report_id`, `chunk_index`, `page_start`, `page_end`, `pages` (as a string), `headings` (joined), `doc_hash`.

**Recommendation:** convert once with `DocumentConverter`, because the same `DoclingDocument` also produces the stored page texts. Chunk with `HybridChunker` and build `langchain_core.documents.Document(id=uuid5(...), page_content=contextualized, metadata=flat)` yourself. This uses LangChain's `Document` and `VectorStore` interfaces where they matter and avoids a second conversion. `DoclingLoader` is the alternative if you prefer the packaged loader, used with a custom `meta_extractor`.

## 4. Vector store: Chroma first, Qdrant later

Versions: `langchain-chroma` 1.1.0 (requires `chromadb>=1.3.5,<2`), `chromadb` 1.5.9, `langchain-qdrant` 1.1.0 (requires `qdrant-client>=1.15.1,<2`), `qdrant-client` 1.20.0 (PyPI).

Documented setup (`/websites/langchain_oss_python_langchain`, oss/python/langchain/knowledge-base):

```python
from langchain_chroma import Chroma

store = Chroma(
    collection_name="report_chunks",
    embedding_function=embeddings,
    persist_directory="./data/chroma",
    collection_configuration={"hnsw": {"space": "cosine"}},
)

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams
from langchain_qdrant import QdrantVectorStore

client = QdrantClient(":memory:")  # or path=..., url=...
client.create_collection("report_chunks", vectors_config=VectorParams(size=dim, distance=Distance.COSINE))
store = QdrantVectorStore(client=client, collection_name="report_chunks", embedding=embeddings)

ids = store.add_documents(documents=chunks, ids=[d.id for d in chunks])
retriever = store.as_retriever(search_type="similarity", search_kwargs={"k": 20, "filter": report_filter(report_id)})
```

**Is `VectorStore` / `as_retriever` a sufficient seam?** Mostly. `add_documents`, `delete(ids)`, `get_by_ids`, `similarity_search[_with_score]`, `max_marginal_relevance_search` and `as_retriever(search_type in {"similarity","mmr","similarity_score_threshold"})` are common to all three stores (langchain_core/vectorstores/in_memory.py; knowledge-base tutorial). What differs, and so must sit behind an app-owned factory:

| Concern | Chroma (`langchain_chroma`) | Qdrant (`langchain_qdrant`) | InMemory (tests) |
|---|---|---|---|
| Metadata filter | `filter: dict` → Chroma `where` (e.g. `{"report_id": "RPT-…"}`; `$and`/`$eq` operators, **UNVERIFIED** against Chroma docs), plus `where_document` for content | `filter: qdrant_client.models.Filter` on payload keys under `metadata.` (e.g. `key="metadata.report_id"`) | `filter: Callable[[Document], bool]` |
| Metadata values | flat scalars only (error hint above) | nested JSON payload allowed | anything |
| Persistence | `persist_directory=` (embedded), `host=` (server) or Chroma Cloud: exactly one | `location=":memory:"`, `path=` (local), `url=` (server) | `dump(path)`/`load(path)` |
| Collection config | `collection_configuration={"hnsw": {"space": "cosine"\|"l2"\|"ip"}}`. **The default relevance function is Euclidean** unless a space is set | `create_collection(vectors_config=VectorParams(size, distance))`; `distance=Distance.COSINE` by default; `force_recreate` | n/a (cosine) |
| IDs | any string; uuid4 generated if omitted | **unsigned int or UUID only** ([Qdrant points](https://qdrant.tech/documentation/manage-data/points/)); uuid4 generated if omitted | any string |
| Score from `similarity_search_with_score` | a **distance** (lower is better), per the tutorial note | a similarity (higher is better) for cosine (**UNVERIFIED** in langchain_qdrant source) | cosine similarity |
| Extras | — | `retrieval_mode=DENSE\|SPARSE\|HYBRID` (sparse + dense hybrid) | — |

Sources: langchain_chroma/vectorstores.py (`__init__`, `_select_relevance_score_fn`, `similarity_search` signatures), langchain_qdrant/qdrant.py (`RetrievalMode`, `distance`, `filter: models.Filter`, `ids: Sequence[str | int]`), both on GitHub master.

Design implications:
- Use `similarity_search_with_relevance_scores` (normalised to higher-is-better through `_select_relevance_score_fn`) if a vector score goes into the audit record. Better still, record the rerank score, which is the one that decides what is kept.
- One collection holds all Reports, filtered by `report_id`. Store the embedding model name and dimension in collection metadata, and refuse to query a collection built with a different model. That answers ADR-0007's "not versioned".
- ADR-0008 (one process on SQLite): an embedded Chroma `persist_directory` (or Qdrant `path=`) keeps one process. The vector index is **derived data**. It can be rebuilt from stored chunks, so the audit chain must not depend on it existing later. Store chunk text in SQLite too (see Decisions).

## 5. Reranking (Cohere cross-encoder)

Versions: `langchain-cohere` 0.6.0 (requires `cohere>=5.18,<6.0`), `cohere` 7.3.2 (PyPI). `ContextualCompressionRetriever` now lives in **`langchain_classic.retrievers`** (`langchain-classic` 1.0.8), not in `langchain` 1.x (GitHub: libs/langchain/langchain_classic/retrievers/contextual_compression.py).

`CohereRerank(BaseDocumentCompressor)` (GitHub langchain-cohere, langchain_cohere/rerank.py):
- Fields: `model` (**mandatory**), `top_n=3`, `cohere_api_key` (env `APP_COHERE_API_KEY`), `base_url`, `client`. A supplied `client` must be a `cohere.ClientV2`.
- `compress_documents` calls `client.rerank(query, documents, model, top_n, max_tokens_per_doc)`. It returns copies of the documents with `metadata["relevance_score"]` added.

```python
from langchain_classic.retrievers import ContextualCompressionRetriever
from langchain_cohere import CohereRerank

reranker = CohereRerank(model="rerank-v3.5", top_n=5)
retriever = ContextualCompressionRetriever(
    base_compressor=reranker, base_retriever=store.as_retriever(search_kwargs={"k": 20, "filter": f})
)
docs = retriever.invoke("Energy sector outlook")  # each doc.metadata["relevance_score"]
```

Models ([Cohere models](https://docs.cohere.com/docs/models)):

| Model | Context | Notes |
|---|---|---|
| `rerank-v5.0-pro` / `rerank-v5.0-fast` | 32k | Latest. "Context Focus" and calibrated scores, which allow one threshold across queries. |
| `rerank-v4.0-pro` / `-fast` | 32k | Previous generation (released 2025-12-11 per the [changelog](https://docs.cohere.com/changelog)). |
| `rerank-v3.5` | 4k | Strong on finance per its release notes (`/websites/cohere` changelog). |

- **API:** `/v2/rerank`, where `model` is required and `max_tokens_per_doc` defaults to 4096 (`/websites/cohere` changelog).
- **Pricing unit:** "one query with up to 100 documents"; any document over 500 tokens (query included) is split into several, each counted ([cohere.com/pricing](https://cohere.com/pricing)). The price per 1K searches is **UNVERIFIED**: it was not in the static page. With 14 subject queries × k=20 chunks of ≤512 tokens, one Report costs about 14 searches (some chunks may split).
- **Latency:** no primary figure found. **UNVERIFIED.**
- **Whether `langchain-cohere` 0.6.0 exposes Rerank 5's Context Focus:** **UNVERIFIED**. It passes only `model`, `top_n` and `max_tokens_per_doc`, so probably not.
- **Via OpenRouter:**
  - `POST https://openrouter.ai/api/v1/rerank` with `{model:"cohere/rerank-v3.5", query, documents, top_n}` returns `results[{index, relevance_score, document}]` ([OpenRouter RAG cookbook](https://openrouter.ai/docs/cookbook/evaluate-and-optimize/rag.md)).
  - The `openrouter` Python SDK, already a dependency via `langchain-openrouter`, has `open_router.rerank.rerank(documents, model, query, top_n, provider, retries)` ([SDK rerank](https://openrouter.ai/docs/client-sdks/python/sdks/rerank/README.md)).
  - The model list includes `cohere/rerank-v3.5`, `cohere/rerank-4-pro|fast`, `cohere/rerank-5-pro|fast`, `qwen/qwen3-reranker-*` and others (`GET /api/v1/models`). Cohere's own docs map `rerank-v5.0-pro` → `cohere/rerank-5-pro` on OpenRouter.
  - There is no LangChain integration for OpenRouter rerank; you would write a roughly 20-line `BaseDocumentCompressor`.
- **Retries:** whether the Cohere SDK retries by default is **UNVERIFIED**. If the "no hidden retries" rule (ADR-0011) should extend to rerank, build `cohere.ClientV2` explicitly and pass `client=`.

## 6. Embeddings (provider-agnostic, OpenRouter default)

- **OpenRouter provides embeddings.** `POST https://openrouter.ai/api/v1/embeddings {model, input}`, and `GET /api/v1/embeddings/models` lists them ([OpenRouter embeddings](https://openrouter.ai/docs/api/reference/embeddings.md)). Live on 2026-11-19 there were 38 models, including:

| Model | Context | $/token (prompt) |
|---|---|---|
| `openai/text-embedding-3-small` | 8192 | 2e-8 |
| `openai/text-embedding-3-large` | 8192 | 1.3e-7 |
| `cohere/embed-5-fast` | 128k | 8e-8 |
| `qwen/qwen3-embedding-8b` | 40960 | 1e-8 |
| `baai/bge-m3` | 8194 | 1e-8 |
| `google/gemini-embedding-001` | 20000 | 1.5e-7 |

- **LangChain path:** `langchain-openrouter` 0.3.0 has **no embeddings class**; the wheel contains only `chat_models.py`. The documented route is `langchain_openai.OpenAIEmbeddings` pointed at OpenRouter. Its docstring says: "When using a non-OpenAI provider, set `check_embedding_ctx_length=False` to send raw text instead of tokens" (langchain_openai/embeddings/base.py on GitHub).
- **`init_embeddings("provider:model")`** (`langchain.embeddings`) supports `openai`, `azure_openai`, `bedrock`, `cohere`, `google_genai`, `google_vertexai`, `huggingface`, `mistralai`, `ollama`, … but **not `openrouter`** (GitHub: libs/langchain_v1/langchain/embeddings/base.py). Use `init_embeddings("openai:openai/text-embedding-3-small", base_url=…, check_embedding_ctx_length=False)`, or construct `OpenAIEmbeddings` directly. Whether `init_embeddings` forwards those kwargs is **UNVERIFIED**.
- **Local option:** `HuggingFaceEmbeddings(model_name="sentence-transformers/all-mpnet-base-v2", encode_kwargs={"normalize_embeddings": True})` (`langchain-huggingface` 1.2.3; knowledge-base tutorial). No network, but torch is needed (Docling already brings it).
- **Tokenizer alignment:** for `openai/text-embedding-3-*`, use Docling's `OpenAITokenizer` with tiktoken `cl100k_base`, the encoding those models use (**UNVERIFIED** in a primary source here). For HF models, use `HuggingFaceTokenizer.from_pretrained(model_name=<same id>)`.

```python
from langchain_openai import OpenAIEmbeddings


def get_embeddings(settings) -> Embeddings:
    return OpenAIEmbeddings(
        model=settings.embedding_model,  # "openai/text-embedding-3-small"
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        check_embedding_ctx_length=False,
        max_retries=0,
    )
```

## 7. LangGraph: retrieve → rerank → generate, with provenance

The LangGraph docs' patterns: typed `StateGraph` state, a node per step, edges START→…→END, and `llm.with_structured_output(Schema)` in a node (`/websites/langchain_oss_python_langgraph`, oss/python/langgraph/workflows-agents). LangGraph's documented RAG examples are agentic: a retriever as a tool, then grade and rewrite. Here the query set is fixed, so the **prompt-chaining workflow** is the right documented pattern, not the agent one. That keeps one model request per run, as the LangGraph AI-layer spec requires ("There is no retry loop: one model request per run").

```python
class InsightState(TypedDict):
    report_id: str
    queries: list[RetrievalQuery]  # one per taxonomy subject, built by code
    candidates: NotRequired[list[Document]]  # vector hits, k per query
    selected: NotRequired[list[Document]]  # reranked, top_n per query, de-duplicated by chunk id
    request: NotRequired[LlmRequest]
    content: NotRequired[dict]


def retrieve(state, runtime: Runtime[RagContext]) -> dict:
    f = runtime.context.report_filter(state["report_id"])
    hits = [d for q in state["queries"] for d in runtime.context.store.similarity_search(q.text, k=20, filter=f)]
    return {"candidates": hits}


def rerank(state, runtime) -> dict:  # or one ContextualCompressionRetriever per query in `retrieve`
    ...  # runtime.context.reranker.compress_documents(per_query_hits, q.text) -> relevance_score in metadata
    return {"selected": deduped_top_n}


def generate(state, runtime) -> dict:  # the existing node, unchanged: one structured-output call
    ...


graph = (
    StateGraph(InsightState, context_schema=RagContext)
    .add_node("retrieve", retrieve)
    .add_node("rerank", rerank)
    .add_node("generate", generate)
    .add_edge(START, "retrieve")
    .add_edge("retrieve", "rerank")
    .add_edge("rerank", "generate")
    .add_edge("generate", END)
    .compile(name="insight_extraction")
)
```

- **What the model sees:** the selected chunks, each labelled `[Chunk <uuid> · pages 3-4 · <headings>]`. The output schema gains `chunk_id`, and the prompt version is bumped (`insight_extraction@v2`). Deterministic code checks four things:
  - `chunk_id` was among those shown;
  - `passage` is a substring of that chunk's text;
  - the passage's page, taken from the chunk's provenance rather than the model, exists;
  - `passage_on_page` holds against the Docling page text.
  The model then no longer chooses `page` at all, which is a stronger guarantee than today's.
- **Provenance capture options:**
  1. **Retriever callbacks** (`BaseCallbackHandler.on_retriever_start(serialized, query, *, run_id, metadata)`, `on_retriever_end(documents, *, run_id)`; langchain_core/callbacks/base.py). These fire when retrieval goes through a `BaseRetriever` (`as_retriever()` / `ContextualCompressionRetriever`), with `langgraph_node` in the metadata like the chat-model callback. A `RetrievalCapture` handler beside `ExchangeCapture` would record each query's returned chunk ids and `relevance_score`. Plain `store.similarity_search` calls fire no callbacks: they are not Runnables.
  2. **State**, which is simpler and needs no callback: the `retrieve`/`rerank` nodes put `(query, chunk_id, pages, vector_score, rerank_score, rank)` in state, and the step code writes them to the Audit Event payload or a `retrievals` table.
  **Recommendation:** option 2. It is deterministic, visible in the graph, and needs no extra callback semantics. Use option 1 only if you want retrieval to look like Exchanges.
- **Audit Event payload** (shape proposal): `insight_extracted.payload = {outcome, insight_count, dropped, exchanges:[…], retrieval:{index_version, embedding_model, rerank_model, chunker:{name:"HybridChunker", max_tokens:512, tokenizer:"cl100k_base", serializer:"markdown-tables"}, queries:[{subject, text, hits:[{chunk_id, pages, rank, rerank_score}]}]}}`. Each `InsightRow` gains `chunk_id`. Lineage becomes Report → chunk → Insight → Research Tilt.
- **Chunk storage for the Auditor:** store each chunk's text and hash in SQLite (a `report_chunks` table, for example). The audit trail then never depends on the vector store, which can be rebuilt from SQLite plus the embedding model. The Exchange already holds the exact chunk text the model saw.

## 8. Offline testing

- `DeterministicFakeEmbedding(size=N)`: the same text gives the same vector (hash-seeded). `FakeEmbeddings` is random per call, so it is useless for retrieval assertions (langchain_core/embeddings/fake.py on GitHub).
- `InMemoryVectorStore(embedding)` (`langchain_core.vectorstores`) supports `add_documents(ids=…)`, `get_by_ids`, `similarity_search(filter=callable)`, `as_retriever` and `dump`/`load` (langchain_core/vectorstores/in_memory.py).
  - Caveat: deterministic fake vectors are not semantic, so a test cannot assert "the Energy query finds the Energy chunk" by similarity.
  - For routing tests, script the retrieval instead: a fake retriever, or `FakeEmbeddings`-free fixtures with hand-set vectors.
  - Or keep k ≥ the chunk count so every chunk is a candidate and the **reranker fake** decides.
- **Fake reranker:** subclass `BaseDocumentCompressor` and return documents in a scripted order with a scripted `relevance_score`. `CohereRerank` checks `isinstance(client, cohere.ClientV2)`, so a duck-typed client is rejected (rerank.py). Faking at the compressor seam is the standard LangChain seam (`ContextualCompressionRetriever(base_compressor=…)`).
- **Chat model:** the existing `tests/fake_chat.py` `FakeChatModel` (in the main checkout) already scripts `with_structured_output(method="json_schema")` replies.
- **Docling in tests:** convert Markdown/DOCX fixtures (SimplePipeline, no model download), or commit a `DoclingDocument` JSON (`DoclingDocument.model_validate_json`; method name **UNVERIFIED**, since it is Pydantic). Keep a PDF conversion test behind `LLM_LIVE=1`-style gating, or behind pre-fetched `artifacts_path`.

## 9. RAG evaluation (brief)

- **Retrieval metrics, in plain pytest:** a small labelled set of 2-3 Reports, with `(subject → gold chunk ids)` or `(subject → gold passage)`. Compute **hit-rate@k** (a gold chunk is in the top-k) and **MRR**. Run it on the fake stack for regressions and live (`LLM_LIVE=1`) to compare chunk size, k, top_n and rerank on/off. These metrics are standard, and computing them needs no library.
- **End-to-end:** today's checks already act as faithfulness metrics (the passage is verbatim on its cited page, the subject is in the taxonomy). Track kept/dropped ratios per Report.
- **RAGAS** (`ragas` 0.4.4):
  - Current docs evaluate a LangChain app with `LLMContextRecall`, `Faithfulness` and `FactualCorrectness`, wrapping the judge as `LangchainLLMWrapper(llm)` ([docs.ragas.io LangChain integration](https://docs.ragas.io/en/latest/howtos/integrations/langchain/)). Context precision and recall are also available.
  - Its dependencies include `langchain-community`, `datasets`, `instructor` and `openai` (PyPI), so put it in an optional dependency group and a script, not the test suite.
  - RAGAS is designed for Q&A. Insight extraction is closer to a classification and extraction task, so the labelled hit-rate set is the more useful measure.

## Decisions the user must make

1. **Supersede ADR-0007's RAG rejection with ADR-0012.** *Default: yes.* Answer its three points:
   - Reports fit in one prompt: RAG is a demonstrator capability and precision gain, not a size necessity, so say so.
   - Versioning: record the embedding model, chunker config and index version in every `insight_extracted` event.
   - Auditor visibility: retrieval provenance plus chunk text in SQLite.
2. **Query design.** *Default: one fixed query per taxonomy subject (14), built by code from `GICS_SECTORS`/`ASSET_CLASSES`.* The alternative, an LLM-generated query, adds a model call and nondeterminism.
3. **One generate call or one per subject.** *Default: one call over the de-duplicated union of reranked chunks*: a Trajectory of one Exchange, and the spec's "one model request per run". Per-subject calls give cleaner context but make 14 Exchanges.
4. **Recall safety net.** Retrieval can miss a view the full-text prompt would have caught. *Default: if the Report fits under a token budget, also accept a "no retrieval" mode for comparison in eval only; ship RAG-only.* Measure missed Insights against the current full-text extraction on the seeded Reports before switching.
5. **Rerank provider.** *Default: `CohereRerank(model="rerank-v3.5", top_n=5)` direct to Cohere* (the documented LangChain path; adds `APP_COHERE_API_KEY`). The alternative is OpenRouter `/api/v1/rerank` through a small custom compressor: one key and one gateway, but hand-written. Also consider `rerank-v5.0-fast` for newer quality and calibrated scores.
6. **Embedding model.** *Default: `openai/text-embedding-3-small` via OpenRouter* (cheap, 8k context, tiktoken-aligned). The offline alternative is a local HF model.
7. **Vector store persistence.** *Default: Chroma embedded `persist_directory` under the app data directory, one collection, filtered by `report_id`*, with chunks also stored in SQLite so the index is rebuildable. Qdrant later via the same factory.
8. **Docling scope.** *Defaults:*
   - tables on, in ACCURATE mode;
   - OCR on, which lifts "scanned PDFs are not supported";
   - **picture description off in v1**, because a Docling VLM call would bypass Exchange capture. If wanted, route it through a captured LangChain call instead of `PictureDescriptionApiOptions`.
9. **Chunk parameters.** *Default: `HybridChunker`, 512 tokens, `merge_peers=True`, Markdown tables, `contextualize()` text embedded.* Tune with the hit-rate eval.
10. **Use `DoclingLoader` or not.** *Default: no.* Use `DocumentConverter` + `HybridChunker` directly so one `DoclingDocument` feeds both chunks and stored page texts, wrapped in LangChain `Document`s. Use the loader only with a flat `meta_extractor`.
11. **Install weight.** Docling brings PyTorch and model downloads. *Default: accept, pre-fetch models in setup (`docling-tools models download`), and keep tests on Markdown/DOCX fixtures.*
12. **Reranker retries.** *Default: build `cohere.ClientV2` explicitly with retries off*, matching ADR-0011's "every request is one we see". Cohere's SDK retry defaults are **UNVERIFIED**.

## Sources

Code read (this worktree): `app/reports.py`, `app/prompts.py`, `app/llm.py`, `app/llm_graph.py`, `app/exchanges.py`, `app/chat_model.py`, `app/db.py`, `app/routers/reports.py`, `tests/test_research.py`, `docs/adr/0007-…md`, `GLOSSARY.md`, and the main checkout's `.scratch/langgraph-ai-layer/spec.md` and `tests/fake_chat.py`.

Context7:
- `/docling-project/docling`: chunking concepts, rag_topk, rag_opensearch, rag_mongodb, pipeline_options.py, enrichments.md, advanced_options.md, cli.md, supported_formats.md, installation.md, document_converter.py
- `/docling-project/docling-core`: reference.py, node.py, hierarchical_chunker.py, document.py, chunker `__init__`
- `/docling-project/docling-langchain`: loader.md, docling_loader.ipynb
- `/websites/langchain_oss_python_langchain`: knowledge-base, models, messages
- `/websites/langchain_oss_python_langgraph`: workflows-agents, overview, add-memory
- `/websites/cohere`: changelog, rerank v4/v3.5, `/v2/rerank`

Source code (GitHub, master/main on 2026-11-19):
- https://github.com/langchain-ai/langchain-cohere/blob/main/libs/cohere/langchain_cohere/rerank.py
- https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain_classic/retrievers/contextual_compression.py
- https://github.com/langchain-ai/langchain/blob/master/libs/langchain/langchain_classic/retrievers/parent_document_retriever.py
- https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/embeddings/fake.py
- https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/vectorstores/in_memory.py
- https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/callbacks/base.py
- https://github.com/langchain-ai/langchain/blob/master/libs/partners/chroma/langchain_chroma/vectorstores.py
- https://github.com/langchain-ai/langchain/blob/master/libs/partners/qdrant/langchain_qdrant/qdrant.py
- https://github.com/langchain-ai/langchain/blob/master/libs/partners/openai/langchain_openai/embeddings/base.py
- https://github.com/langchain-ai/langchain/blob/master/libs/langchain_v1/langchain/embeddings/base.py
- https://github.com/langchain-ai/langchain-experimental/blob/main/libs/experimental/langchain_experimental/text_splitter.py
- https://github.com/docling-project/docling-core/blob/main/docling_core/transforms/chunker/tokenizer/openai.py
- `langchain-openrouter` 0.3.0 wheel contents (PyPI)

Docs and web:
- https://openrouter.ai/docs/api/reference/embeddings.md
- https://openrouter.ai/api/v1/embeddings/models (live list)
- https://openrouter.ai/api/v1/models (rerank model ids)
- https://openrouter.ai/docs/cookbook/evaluate-and-optimize/rag.md
- https://openrouter.ai/docs/client-sdks/python/sdks/rerank/README.md
- https://docs.cohere.com/docs/models
- https://docs.cohere.com/changelog
- https://cohere.com/pricing
- https://qdrant.tech/documentation/manage-data/points/
- https://docs.ragas.io/en/latest/howtos/integrations/langchain/

PyPI (versions, requires_dist): docling, docling-slim, docling-core, langchain-docling, langchain-chroma, chromadb, langchain-qdrant, qdrant-client, langchain-cohere, cohere, langchain, langchain-core, langchain-classic, langgraph, langchain-text-splitters, langchain-experimental, langchain-openrouter, langchain-openai, langchain-huggingface, sentence-transformers, ragas.
