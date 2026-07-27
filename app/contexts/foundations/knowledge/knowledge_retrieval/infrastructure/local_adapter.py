"""In-process Knowledge Search adapter.

Phase 2 的 ``RemoteKnowledgeAdapter`` 将实现同一 ``KnowledgeSearchPort``；消费方经
``public.build_local_knowledge_search_port`` 拿端口，绝不直连本文件。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_retrieval.application.use_cases import (
    KnowledgeRetrieval,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure import (
    sqlalchemy_gateway,
)


class LocalKnowledgeSearchAdapter:
    """会话绑定的本地检索端口——满足 ``KnowledgeSearchPort``。

    端口方法本身会话无关（利于远端替换）；本地实现在构造期绑定调用方 session，
    以保留事务与数据可见性，避免全局 session 带来的测试/隔离意外。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._retrieval = KnowledgeRetrieval(
            sqlalchemy_gateway.SqlAlchemyKnowledgeRetrievalGateway(session)
        )

    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult:
        return await self._retrieval.search(query)
