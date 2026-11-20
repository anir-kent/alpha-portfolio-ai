"""The Report Index (ADR-0012): a Report's Chunks, in SQLite as the record of truth and embedded in a vector store.

Docling converts an upload and `HybridChunker` splits it, through LangChain's documented `DoclingLoader` in
`DOC_CHUNKS` mode. Each Chunk gets a uuid5 id and flat metadata (Chroma accepts nothing nested), and the page texts shown
to the reviewer come from the same Docling conversion. `get_vector_store` and `report_filter` are the only places that
know which vector store backend is configured.
"""

import io
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cohere
import tiktoken
from docling.chunking import HybridChunker
from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode, TableStructureOptions
from docling.document_converter import DocumentConverter, ImageFormatOption, PdfFormatOption
from docling_core.transforms.chunker.hierarchical_chunker import ChunkingDocSerializer, ChunkingSerializerProvider
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
from docling_core.transforms.serializer.markdown import MarkdownTableSerializer
from docling_core.types.doc import DoclingDocument
from langchain_cohere import CohereRerank
from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import InMemoryVectorStore, VectorStore
from langchain_docling import DoclingLoader
from langchain_docling.loader import BaseMetaExtractor, ExportType
from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr
from pypdf import PdfReader
from tiktoken.model import encoding_name_for_model

from app.settings import Settings

MAX_PAGES = 50
MAX_BYTES = 20 * 1024 * 1024
CHUNK_MAX_TOKENS = 512
COLLECTION = "report_chunks"
HEADING_SEPARATOR = " > "
# What each upload type is stored as. Docling reads Markdown; plain text is Markdown without markup.
KINDS = {
    ".pdf": "pdf",
    ".docx": "docx",
    ".pptx": "pptx",
    ".md": "text",
    ".txt": "text",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
}
IMAGE_MAGIC = {".png": b"\x89PNG", ".jpg": b"\xff\xd8", ".jpeg": b"\xff\xd8"}
CHUNK_NAMESPACE = uuid.UUID("5e0c6a3e-6d3b-4a8e-9c52-3f1d7a3b9a10")


class ReportError(Exception):
    """The upload cannot be turned into a Report."""


class ReportTooLarge(ReportError):
    """The upload is over the size or page limit."""


def chunk_id(report_id: str, index: int) -> str:
    """A Chunk's stable id: the same Report and index always give the same id, so re-indexing is idempotent."""
    return str(uuid.uuid5(CHUNK_NAMESPACE, f"{report_id}:{index}"))


@dataclass(frozen=True)
class ReportChunk:
    id: str
    index: int
    page: int
    headings: str
    text: str


@dataclass(frozen=True)
class ParsedReport:
    kind: str
    pages: list[str]  # Markdown per page; one entry for a format with no pages
    chunks: list[ReportChunk]


def encoding_name(embedding_model: str) -> str:
    try:  # the name only: loading an encoding fetches it from the network on first use
        return encoding_name_for_model(embedding_model.rsplit("/", 1)[-1])
    except KeyError:
        return "cl100k_base"


def chunk_tokenizer(embedding_model: str) -> BaseTokenizer:
    """The tokenizer the chunker counts with, aligned to the embedding model (tiktoken)."""
    return OpenAITokenizer(tokenizer=tiktoken.get_encoding(encoding_name(embedding_model)), max_tokens=CHUNK_MAX_TOKENS)


def chunker_config(embedding_model: str) -> dict:
    """What produced the Chunks, recorded in Retrieval Provenance."""
    return {
        "chunker": "docling.HybridChunker",
        "max_tokens": CHUNK_MAX_TOKENS,
        "merge_peers": True,
        "tokenizer": f"tiktoken:{encoding_name(embedding_model)}",
        "tables": "markdown",
    }


class _MarkdownTables(ChunkingSerializerProvider):
    """Chunks carry tables as Markdown, the form a model reads best (Docling's default is triplet notation)."""

    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(doc=doc, table_serializer=MarkdownTableSerializer())


class _FlatMeta(BaseMetaExtractor):
    """Docling's chunk metadata is nested JSON, which Chroma rejects: keep the page and the headings, flat."""

    def extract_chunk_meta(self, file_path: str, chunk: Any) -> dict[str, Any]:
        pages = sorted({p.page_no for item in chunk.meta.doc_items for p in item.prov})
        return {"page": pages[0] if pages else 1, "headings": HEADING_SEPARATOR.join(chunk.meta.headings or [])}

    def extract_dl_doc_meta(self, file_path: str, dl_doc: DoclingDocument) -> dict[str, Any]:
        return {}


class _Recording:
    """A `DoclingLoader` converter that keeps the `DoclingDocument` it converted, so the page texts come from the same
    conversion as the Chunks."""

    def __init__(self, inner: DocumentConverter):
        self._inner = inner
        self.document: DoclingDocument | None = None

    @property
    def convert(self):
        def convert(*args: Any, **kwargs: Any):
            result = self._inner.convert(*args, **kwargs)
            self.document = result.document
            return result

        return convert


def build_converter() -> DocumentConverter:
    """Tables on (ACCURATE mode) and OCR on; picture description stays off, since Docling's own vision-model call would
    bypass Exchange capture (ADR-0012)."""
    pdf = PdfPipelineOptions(
        do_ocr=True,
        do_table_structure=True,
        table_structure_options=TableStructureOptions(mode=TableFormerMode.ACCURATE),
        do_picture_description=False,
    )
    return DocumentConverter(
        allowed_formats=[InputFormat.PDF, InputFormat.IMAGE, InputFormat.DOCX, InputFormat.PPTX, InputFormat.MD],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pdf),
            InputFormat.IMAGE: ImageFormatOption(pipeline_options=pdf),  # an image is OCRed like a scanned page
        },
    )


def _page_texts(doc: DoclingDocument) -> list[str]:
    numbers = sorted(doc.pages)
    if not numbers:  # DOCX and Markdown carry no page boundaries: the whole document is one page
        return [doc.export_to_markdown()]
    return [doc.export_to_markdown(page_no=n) for n in numbers]


def _checked(filename: str, content: bytes) -> tuple[str, str]:
    """(suffix Docling reads the file as, kind), or `ReportError`."""
    suffix = Path(filename.lower()).suffix
    if suffix not in KINDS:
        raise ReportError(
            "Only PDF, DOCX, PPTX, Markdown or text (.pdf, .docx, .pptx, .md, .txt) Reports are supported"
        )
    if suffix == ".pdf" and not content.startswith(b"%PDF"):
        raise ReportError("File is not a valid PDF")
    if suffix in IMAGE_MAGIC and not content.startswith(IMAGE_MAGIC[suffix]):
        raise ReportError(f"File is not a valid {suffix[1:].upper()} image")
    if suffix in (".docx", ".pptx") and not content.startswith(b"PK"):
        raise ReportError(f"File is not a valid {suffix[1:].upper()}")
    if suffix in (".md", ".txt"):
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            raise ReportError("Text Reports must be UTF-8") from None
    return (".md" if suffix == ".txt" else suffix), KINDS[suffix]


def check_upload(filename: str, content: bytes) -> str:
    """The kind of an acceptable upload, checked cheaply so the request can refuse it before any background work: type,
    magic bytes, text encoding, and (for a PDF, whose pages are countable without Docling) the page limit. Raises
    `ReportError`, or `ReportTooLarge` over a limit."""
    suffix, kind = _checked(filename, content)
    if len(content) > MAX_BYTES:
        raise ReportTooLarge(f"Report file is too large (limit {MAX_BYTES // (1024 * 1024)} MB)")
    if suffix == ".md" and not content.strip():
        raise ReportError("Report contains no extractable text")
    if suffix == ".pdf":
        try:
            pages = len(PdfReader(io.BytesIO(content)).pages)
        except Exception as e:  # pypdf raises several error types on a damaged file
            raise ReportError(f"Could not read PDF: {e}") from e
        if pages > MAX_PAGES:
            raise ReportTooLarge(f"Report is too long (limit {MAX_PAGES} pages)")
    return kind


def parse_report(
    filename: str,
    content: bytes,
    *,
    report_id: str,
    embedding_model: str,
    converter: DocumentConverter | None = None,
) -> ParsedReport:
    """Converts and chunks an upload. Raises `ReportError` when it cannot be read or holds no text."""
    suffix, kind = _checked(filename, content)
    if suffix == ".md":  # plain text and Markdown both go through Docling's Markdown reader; a form feed is a break
        content = content.replace(b"\f", b"\n\n")
    recording = _Recording(converter or build_converter())
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / f"report{suffix}"
        path.write_bytes(content)
        try:
            documents = DoclingLoader(
                file_path=str(path),
                converter=recording,
                convert_kwargs={"max_num_pages": MAX_PAGES, "max_file_size": MAX_BYTES},
                export_type=ExportType.DOC_CHUNKS,
                chunker=HybridChunker(
                    tokenizer=chunk_tokenizer(embedding_model), merge_peers=True, serializer_provider=_MarkdownTables()
                ),
                meta_extractor=_FlatMeta(),
            ).load()
        except Exception as e:
            raise ReportError(f"Could not read {kind.upper()}: {e}") from e
    document = recording.document
    chunks = [
        ReportChunk(
            id=chunk_id(report_id, i),
            index=i,
            page=d.metadata["page"],
            headings=d.metadata["headings"],
            text=d.page_content,
        )
        for i, d in enumerate(d for d in documents if d.page_content.strip())
    ]
    if document is None or not chunks:
        raise ReportError("Report contains no extractable text")
    pages = _page_texts(document)
    if len(pages) > MAX_PAGES:
        raise ReportError(f"Report is too long (limit {MAX_PAGES} pages)")
    return ParsedReport(kind=kind, pages=pages, chunks=chunks)


def chunk_pages(
    pages: list[str], *, report_id: str, embedding_model: str, converter: DocumentConverter | None = None
) -> list[ReportChunk]:
    """Chunks a stored Report from its page texts, which are Markdown, through the same Docling Markdown path as an
    upload (`parse_report`). Each page is chunked on its own, so every Chunk keeps its page number; ids run on across
    pages. A page with no text gives no Chunks. Raises `ReportError` when the Report has none at all."""
    converter = converter or build_converter()
    chunks: list[ReportChunk] = []
    for page, text in enumerate(pages, 1):
        try:
            parsed = parse_report(
                "page.md", text.encode(), report_id=report_id, embedding_model=embedding_model, converter=converter
            )
        except ReportError:  # a blank page
            continue
        for c in parsed.chunks:
            index = len(chunks)
            chunks.append(
                ReportChunk(id=chunk_id(report_id, index), index=index, page=page, headings=c.headings, text=c.text)
            )
    if not chunks:
        raise ReportError("Report contains no extractable text")
    return chunks


def chunk_documents(report_id: str, chunks: list[ReportChunk]) -> list[Document]:
    """The Chunks as the vector store holds them: flat metadata, the Chunk id as the document id."""
    return [
        Document(
            id=c.id,
            page_content=c.text,
            metadata={
                "report_id": report_id,
                "chunk_id": c.id,
                "chunk_index": c.index,
                "page": c.page,
                "headings": c.headings,
            },
        )
        for c in chunks
    ]


def get_embeddings(settings: Settings) -> Embeddings:
    """Embeddings through the OpenAI-compatible endpoint the chat model uses. SDK retries are off, as for the chat model."""
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        openai_api_key=SecretStr(settings.llm_api_key),
        openai_api_base=settings.llm_base_url,
        check_embedding_ctx_length=False,  # a gateway's models are not tiktoken-known: send the text as is
        max_retries=0,
    )


class NoRetryClientV2(cohere.ClientV2):
    """The Cohere client with SDK retries off: its default is two retries per request, hidden from the audit trail (the
    same rule as the chat model's `max_retries=0`, ADR-0011). A failed rerank fails the extraction."""

    def rerank(self, *, request_options: Any = None, **kwargs: Any) -> Any:
        return super().rerank(request_options={**(request_options or {}), "max_retries": 0}, **kwargs)


def get_reranker(settings: Settings) -> BaseDocumentCompressor:
    """Cohere's cross-encoder, keeping `rerank_top_n` Chunks per query. Raises `RuntimeError` when no key is set."""
    if not settings.cohere_api_key:
        raise RuntimeError("APP_COHERE_API_KEY must be set to rerank Chunks")
    return CohereRerank(
        model=settings.rerank_model,
        top_n=settings.rerank_top_n,
        client=NoRetryClientV2(settings.cohere_api_key, client_name="langchain:partner"),
    )


def get_vector_store(settings: Settings, embeddings: Embeddings | None = None) -> VectorStore:
    """The vector store `settings` configure: the one place that knows the backend. Every backend is cosine."""
    embeddings = embeddings or get_embeddings(settings)
    if settings.vector_store == "memory":
        return InMemoryVectorStore(embeddings)
    if settings.vector_store == "qdrant":
        from langchain_qdrant import QdrantVectorStore
        from qdrant_client import QdrantClient, models

        # A server when `qdrant_url` is set, else embedded on disk (or in memory for ":memory:").
        client = (
            QdrantClient(url=settings.qdrant_url) if settings.qdrant_url else QdrantClient(path=settings.qdrant_dir)
        )
        if not client.collection_exists(COLLECTION):
            size = len(embeddings.embed_query("dimension probe"))
            client.create_collection(
                COLLECTION, vectors_config=models.VectorParams(size=size, distance=models.Distance.COSINE)
            )
        return QdrantVectorStore(
            client=client, collection_name=COLLECTION, embedding=embeddings, distance=models.Distance.COSINE
        )
    import chromadb
    from langchain_chroma import Chroma

    return Chroma(
        collection_name=COLLECTION,
        embedding_function=embeddings,
        client_settings=chromadb.config.Settings(
            is_persistent=True, persist_directory=settings.chroma_dir, anonymized_telemetry=False
        ),
        collection_configuration={"hnsw": {"space": "cosine"}},
    )


def drop_vector_store(settings: Settings, store: VectorStore) -> None:
    """Deletes the collection `get_vector_store` made; it is created again, empty, the next time it is asked for."""
    if settings.vector_store == "chroma":
        store.delete_collection()  # type: ignore[attr-defined]
    elif settings.vector_store == "qdrant":
        store.client.delete_collection(COLLECTION)  # type: ignore[attr-defined]
    # memory: dropping the object is enough


def report_filter(settings: Settings, report_id: str) -> Any:
    """The backend's own filter for one Report's Chunks."""
    if settings.vector_store == "memory":
        return lambda doc: doc.metadata.get("report_id") == report_id
    if settings.vector_store == "qdrant":
        from qdrant_client import models

        # langchain-qdrant keeps a Document's metadata under the payload key `metadata`.
        return models.Filter(
            must=[models.FieldCondition(key="metadata.report_id", match=models.MatchValue(value=report_id))]
        )
    return {"report_id": report_id}


class ReportIndex:
    """The app's vector store, built on first use so the app starts without an embedding key; a test sets `vector_store`
    to one on fake embeddings."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._store: VectorStore | None = None
        self._reranker: BaseDocumentCompressor | None = None

    @property
    def vector_store(self) -> VectorStore:
        if self._store is None:
            self._store = get_vector_store(self.settings)
        return self._store

    @vector_store.setter
    def vector_store(self, store: VectorStore) -> None:
        self._store = store

    @property
    def reranker(self) -> BaseDocumentCompressor:
        if self._reranker is None:
            self._reranker = get_reranker(self.settings)
        return self._reranker

    @reranker.setter
    def reranker(self, reranker: BaseDocumentCompressor) -> None:
        self._reranker = reranker

    def drop(self) -> None:
        """Deletes the whole collection; the next use creates it empty, so the vector store can be rebuilt from the
        Chunks in SQLite."""
        drop_vector_store(self.settings, self.vector_store)
        self._store = None

    def add(self, report_id: str, chunks: list[ReportChunk]) -> None:
        self.vector_store.add_documents(chunk_documents(report_id, chunks), ids=[c.id for c in chunks])

    def report_filter(self, report_id: str) -> Any:
        return report_filter(self.settings, report_id)
