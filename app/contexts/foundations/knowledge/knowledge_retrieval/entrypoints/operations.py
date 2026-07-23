"""Request-scoped Knowledge Retrieval operations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure import (
    sqlalchemy_gateway,
)


def _retrieval(session: AsyncSession) -> KnowledgeRetrieval:
    return KnowledgeRetrieval(sqlalchemy_gateway.SqlAlchemyKnowledgeRetrievalGateway(session))


async def search_knowledge(
    session: AsyncSession, query: SearchKnowledgeQuery
) -> SearchKnowledgeResult:
    return await _retrieval(session).search(query)


async def answer_knowledge(session: AsyncSession, query: AnswerKnowledgeQuery) -> KnowledgeAnswer:
    return await _retrieval(session).answer(query)


async def diagnose_retrieval_arms(
    session: AsyncSession,
    query: SearchKnowledgeQuery,
) -> KnowledgeRetrievalArmDiagnostics:
    return await _retrieval(session).diagnose(query)
