"""Stable Knowledge Indexing application facade for outer adapters."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_indexing.contracts import (
    KnowledgeIndexPort as KnowledgeIndexPort,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    index_feishu_document as index_feishu_document,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    index_file as index_file,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    index_text as index_text,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    list_documents as list_documents,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    move_document as move_document,
)
from app.contexts.foundations.knowledge.knowledge_indexing.entrypoints.operations import (
    remove_document_index as remove_document_index,
)
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure.local_adapter import (
    LocalKnowledgeIndexAdapter,
)


def build_local_knowledge_index_port(session: AsyncSession) -> KnowledgeIndexPort:
    """Build the in-process knowledge write port bound to the caller's session.

    Phase 2 换 ``RemoteKnowledgeIndexAdapter`` 的唯一切换点——跨 Context 写消费方一律经此拿端口。
    """
    return LocalKnowledgeIndexAdapter(session)
