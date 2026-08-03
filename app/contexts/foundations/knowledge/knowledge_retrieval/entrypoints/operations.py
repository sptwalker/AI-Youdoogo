"""Request-scoped Knowledge Retrieval operations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    AnswerKnowledgeQuery,
    KnowledgeAnswer,
    KnowledgeRetrievalArmDiagnostics,
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.composition import (
    build_local_knowledge_retrieval,
)


async def search_knowledge(
    session: AsyncSession, query: SearchKnowledgeQuery
) -> SearchKnowledgeResult:
    return await build_local_knowledge_retrieval(session).search(query)


async def answer_knowledge(session: AsyncSession, query: AnswerKnowledgeQuery) -> KnowledgeAnswer:
    return await build_local_knowledge_retrieval(session).answer(query)


async def diagnose_retrieval_arms(
    session: AsyncSession,
    query: SearchKnowledgeQuery,
) -> KnowledgeRetrievalArmDiagnostics:
    return await build_local_knowledge_retrieval(session).diagnose(query)
