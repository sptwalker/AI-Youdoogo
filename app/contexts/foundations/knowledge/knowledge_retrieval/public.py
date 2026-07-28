"""Stable Knowledge Retrieval application facade for outer adapters."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    KnowledgeRetrievalPort as KnowledgeRetrievalPort,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    KnowledgeSearchPort as KnowledgeSearchPort,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.entrypoints.operations import (
    answer_knowledge as answer_knowledge,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.entrypoints.operations import (
    diagnose_retrieval_arms as diagnose_retrieval_arms,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.entrypoints.operations import (
    search_knowledge as search_knowledge,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.composition import (
    build_local_knowledge_retrieval,
)


def build_local_knowledge_search_port(session: AsyncSession) -> KnowledgeSearchPort:
    return build_local_knowledge_retrieval(session)
