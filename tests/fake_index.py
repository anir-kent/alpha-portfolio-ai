"""Offline doubles for the Report Index (ADR-0012): fake embeddings and a word-count tokenizer, so no test reaches a
provider or downloads a model. The `offline_index` fixture in `tests.conftest` patches them in for every app."""

from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
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
