"""Knowledge Retrieval implementation port."""

from __future__ import annotations

from typing import Protocol

from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    AnswerKnowledgeQuery,
    KnowledgeAnswer,
    KnowledgeRetrievalArmDiagnostics,
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
)


class KnowledgeRetrievalGateway(Protocol):
    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult: ...

    async def answer(self, query: AnswerKnowledgeQuery) -> KnowledgeAnswer: ...

    async def diagnose(self, query: SearchKnowledgeQuery) -> KnowledgeRetrievalArmDiagnostics: ...
