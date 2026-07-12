"""知识库模块（阶段1）：分块 / 向量化 / 入库 / 检索问答。"""

from app.knowledge.chunk import chunk_text
from app.knowledge.embedding import EmbeddingError, embed_query, embed_texts
from app.knowledge.ingest import (
    delete_file,
    ingest_feishu_doc,
    ingest_file,
    ingest_text,
)
from app.knowledge.retrieval import Hit, answer, search

__all__ = [
    "EmbeddingError",
    "Hit",
    "answer",
    "chunk_text",
    "delete_file",
    "embed_query",
    "embed_texts",
    "ingest_feishu_doc",
    "ingest_file",
    "ingest_text",
    "search",
]
