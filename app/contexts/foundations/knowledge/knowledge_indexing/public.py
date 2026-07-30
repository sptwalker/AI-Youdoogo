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
from app.contexts.foundations.knowledge.knowledge_indexing.infrastructure.remote_adapter import (
    RemoteKnowledgeIndexAdapter,
)
from app.core.config import get_settings


def build_local_knowledge_index_port(session: AsyncSession) -> KnowledgeIndexPort:
    """Build the in-process knowledge write port bound to the caller's session.

    Phase 2 换 ``RemoteKnowledgeIndexAdapter`` 的唯一切换点——跨 Context 写消费方一律经此拿端口。
    """
    return LocalKnowledgeIndexAdapter(session)


def build_remote_knowledge_index_port() -> KnowledgeIndexPort:
    """Build the knowledge write port that speaks to the remote knowledge service over HTTP."""
    return RemoteKnowledgeIndexAdapter(base_url=get_settings().knowledge_gateway_url)


def build_knowledge_index_port(session: AsyncSession) -> KnowledgeIndexPort:
    """选择器（Phase 2 写侧唯一切换点）：mode=remote 且配了地址 → Remote，否则 Local。

    默认 local（无服务时安全）；回滚=mode 归 local。写是副作用，不做 canary 抽样
    （按调用随机路由会分裂写真源，违 docs/21 禁双写红线）——硬切换。远程分支忽略 session。
    """
    settings = get_settings()
    if settings.knowledge_index_mode == "remote" and settings.knowledge_gateway_url:
        return build_remote_knowledge_index_port()
    return build_local_knowledge_index_port(session)

