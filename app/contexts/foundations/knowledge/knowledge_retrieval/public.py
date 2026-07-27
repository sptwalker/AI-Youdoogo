"""Stable Knowledge Retrieval application facade for outer adapters."""

from sqlalchemy.ext.asyncio import AsyncSession

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
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.local_adapter import (
    LocalKnowledgeSearchAdapter,
)


def build_local_knowledge_search_port(session: AsyncSession) -> KnowledgeSearchPort:
    """Build the in-process knowledge search port bound to the caller's session.

    Phase 2 换 ``RemoteKnowledgeAdapter`` 的唯一切换点——跨 Context 消费方一律经此拿端口。
    """
    return LocalKnowledgeSearchAdapter(session)

