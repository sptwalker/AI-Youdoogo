"""Knowledge Retrieval application service."""

from __future__ import annotations

from app.contexts.foundations.knowledge.knowledge_retrieval.application.ports import (
    KnowledgeRetrievalGateway,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    AnswerKnowledgeQuery,
    KnowledgeAnswer,
    KnowledgeRetrievalArmDiagnostics,
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
)


class KnowledgeRetrieval:
    def __init__(self, gateway: KnowledgeRetrievalGateway) -> None:
        self._gateway = gateway

    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult:
        if not query.query.strip() or query.top_k <= 0:
            return SearchKnowledgeResult(hits=(), query=query.query)
        return await self._gateway.search(query)

    async def answer(self, query: AnswerKnowledgeQuery) -> KnowledgeAnswer:
        if not query.query.strip() or query.top_k <= 0:
            return KnowledgeAnswer(
                answer="资料不足，无法回答（知识库中未检索到相关内容）。",
                citations=(),
            )
        return await self._gateway.answer(query)

    async def diagnose(self, query: SearchKnowledgeQuery) -> KnowledgeRetrievalArmDiagnostics:
        if not query.query.strip() or query.top_k <= 0:
            empty = SearchKnowledgeResult(hits=(), query=query.query)
            return KnowledgeRetrievalArmDiagnostics(
                vector=empty,
                keyword=empty,
                fused=empty,
            )
        return await self._gateway.diagnose(query)
