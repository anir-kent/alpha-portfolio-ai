"""Offline doubles for the Report Index (ADR-0012): fake embeddings and a word-count tokenizer, so no test reaches a
provider or downloads a model. The `offline_index` fixture in `tests.conftest` patches them in for every app."""

from collections.abc import Sequence

from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from langchain_core.callbacks import Callbacks
from langchain_core.documents import BaseDocumentCompressor, Document
from langchain_core.embeddings import DeterministicFakeEmbedding

EMBEDDING_SIZE = 32


def fake_embeddings(settings=None) -> DeterministicFakeEmbedding:
    return DeterministicFakeEmbedding(size=EMBEDDING_SIZE)


class WordTokenizer(BaseTokenizer):
    """Counts whitespace-separated words: `tiktoken` fetches its encoding from the network on first use."""

    max_tokens: int = 512

    def count_tokens(self, text: str) -> int:
        return len(text.split())

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self):
        return None


def word_tokenizer(embedding_model: str) -> WordTokenizer:
    return WordTokenizer()


class FakeReranker(BaseDocumentCompressor):
    """Stands in for `CohereRerank`: scores each candidate by the words it shares with the query, keeps the best `top_n`
    with `relevance_score` set (as CohereRerank does), and records every call. `fail` makes it raise."""

    top_n: int = 4
    fail: bool = False
    calls: list[tuple[str, list[str]]] = []

    def compress_documents(
        self, documents: Sequence[Document], query: str, callbacks: Callbacks | None = None
    ) -> Sequence[Document]:
        self.calls.append((query, [d.metadata["chunk_id"] for d in documents]))
        if self.fail:
            raise ConnectionError("rerank unavailable")
        words = set(query.lower().split())
        scored = [(len(words & set(d.page_content.lower().split())) / len(words), d) for d in documents]
        scored.sort(key=lambda pair: -pair[0])
        return [
            Document(d.page_content, metadata={**d.metadata, "relevance_score": score})
            for score, d in scored[: self.top_n]
        ]


def fake_reranker(settings) -> FakeReranker:
    return FakeReranker(top_n=settings.rerank_top_n, calls=[])
