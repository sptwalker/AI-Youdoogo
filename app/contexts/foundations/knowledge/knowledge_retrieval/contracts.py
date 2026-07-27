"""Published Knowledge Retrieval query language."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SearchKnowledgeQuery:
    query: str
    top_k: int = 5
    visible_knowledge_base_ids: tuple[uuid.UUID, ...] | None = None


@dataclass(frozen=True, slots=True)
class KnowledgeHit:
    document_id: uuid.UUID
    document_name: str
    chunk_index: int
    content: str
    score_distance: float
    provenance: str = "knowledge_index"


@dataclass(frozen=True, slots=True)
class SearchKnowledgeResult:
    hits: tuple[KnowledgeHit, ...]
    query: str


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalArmDiagnostics:
    vector: SearchKnowledgeResult
    keyword: SearchKnowledgeResult
    fused: SearchKnowledgeResult


@dataclass(frozen=True, slots=True)
class AnswerKnowledgeQuery:
    query: str
    top_k: int = 5
    principal_id: uuid.UUID | None = None
    visible_knowledge_base_ids: tuple[uuid.UUID, ...] | None = None


@dataclass(frozen=True, slots=True)
class Citation:
    index: int
    document_id: uuid.UUID
    document_name: str
    chunk_index: int
    snippet: str = ""


@dataclass(frozen=True, slots=True)
class KnowledgeAnswer:
    answer: str
    citations: tuple[Citation, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "answer": self.answer,
            "sources": [
                {
                    "index": citation.index,
                    "file_id": str(citation.document_id),
                    "file_name": citation.document_name,
                    "chunk_index": citation.chunk_index,
                    "snippet": citation.snippet,
                }
                for citation in self.citations
            ],
        }


class KnowledgeSearchPort(Protocol):
    """跨 Context 可远端替换的知识检索端口（会话无关签名）。

    Phase 2（docs/21 §11「先切只读 Search」）由 RemoteKnowledgeAdapter 实现同一签名，
    届时仅换 ``public.build_local_knowledge_search_port`` 的返回实现即可全量改道。
    """

    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult: ...
