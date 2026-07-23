"""Compatibility facade for the Knowledge embedding gateway."""

from app.contexts.foundations.knowledge.embedding_gateway import _BATCH as _BATCH
from app.contexts.foundations.knowledge.embedding_gateway import (
    EmbeddingError as EmbeddingError,
)
from app.contexts.foundations.knowledge.embedding_gateway import _api_key as _api_key
from app.contexts.foundations.knowledge.embedding_gateway import embed_query as embed_query
from app.contexts.foundations.knowledge.embedding_gateway import embed_texts as embed_texts

__all__ = ["EmbeddingError", "embed_query", "embed_texts"]
