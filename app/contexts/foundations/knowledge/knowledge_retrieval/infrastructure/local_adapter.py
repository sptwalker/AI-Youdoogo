"""In-process adapter for the published Knowledge Retrieval contract."""

from __future__ import annotations

from app.contexts.foundations.knowledge.knowledge_retrieval.application.use_cases import (
    KnowledgeRetrieval,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    AnswerKnowledgeQuery,
    KnowledgeAnswer,
    KnowledgeRetrievalArmDiagnostics,
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
)


class LocalKnowledgeRetrievalAdapter:
    """Keep callers on stable DTOs while reusing the current retrieval use case."""

    def __init__(self, application: KnowledgeRetrieval) -> None:
        self._application = application

    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult:
        return await self._application.search(query)

    async def answer(self, query: AnswerKnowledgeQuery) -> KnowledgeAnswer:
        return await self._application.answer(query)

    async def diagnose(self, query: SearchKnowledgeQuery) -> KnowledgeRetrievalArmDiagnostics:
        return await self._application.diagnose(query)
