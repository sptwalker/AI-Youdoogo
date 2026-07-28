"""In-process Knowledge Indexing (write-side) adapter.

Phase 2 的 ``RemoteKnowledgeIndexAdapter`` 将实现同一 ``KnowledgeIndexPort``；消费方经
``public.build_local_knowledge_index_port`` 拿端口，绝不直连本文件。与只读侧
``LocalKnowledgeSearchAdapter``（[[ADR 0002]] · A1）对称。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_indexing.application.use_cases import (
    KnowledgeIndexing,
)
from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    IndexedDocument,
    IndexTextCommand,
    KnowledgeIndexPort,
)
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure import (
    sqlalchemy_gateway,
)


class LocalKnowledgeIndexAdapter:
    """会话绑定的本地写侧端口——满足 ``KnowledgeIndexPort``。

    端口方法本身会话无关（利于远端替换）；本地实现在构造期绑定调用方 session，保留调用方
    事务边界（不自建 session、不 commit），outbox 驱动的归档仍在其 worker 租约 session 内落库。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._indexing = KnowledgeIndexing(
            sqlalchemy_gateway.SqlAlchemyDocumentIndexGateway(session)
        )

    async def index_text(self, command: IndexTextCommand) -> IndexedDocument:
        return await self._indexing.index_text(command)

    async def remove_document_index(self, document_id: uuid.UUID) -> None:
        await self._indexing.remove(document_id)

    async def list_documents(self, *, limit: int = 100) -> tuple[IndexedDocument, ...]:
        return await self._indexing.list_documents(limit=limit)


def _assert_protocol() -> None:
    # ponytail: 编译期协议符合性检查，运行时不执行
    _: KnowledgeIndexPort = LocalKnowledgeIndexAdapter.__new__(LocalKnowledgeIndexAdapter)
