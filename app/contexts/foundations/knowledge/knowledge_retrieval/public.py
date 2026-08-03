"""Stable Knowledge Retrieval application facade for outer adapters."""

import secrets
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    KnowledgeRetrievalPort as KnowledgeRetrievalPort,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    KnowledgeSearchPort as KnowledgeSearchPort,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    SearchKnowledgeQuery,
    SearchKnowledgeResult,
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
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure.remote_adapter import (
    RemoteKnowledgeSearchAdapter,
)
from app.core.config import get_settings


class _RoutedKnowledgeSearchPort(Protocol):
    """Narrow boundary implemented by both the local facade and search-only remote adapter."""

    async def search(self, query: SearchKnowledgeQuery) -> SearchKnowledgeResult: ...


def build_local_knowledge_search_port(session: AsyncSession) -> KnowledgeSearchPort:
    """Build the in-process knowledge search port bound to the caller's session."""
    return build_local_knowledge_retrieval(session)


def build_remote_knowledge_search_port() -> _RoutedKnowledgeSearchPort:
    """Build the knowledge search port that speaks to the remote knowledge service over HTTP."""
    return RemoteKnowledgeSearchAdapter(base_url=get_settings().knowledge_gateway_url)


def _route_remote(percent: int) -> bool:
    """按调用抽样决定本次是否走远程知识服务（同 LLM canary 语义）。

    percent=0 恒 local（生产默认，安全）；100 恒 remote；0<p<100 按 p% 概率抽样。
    ponytail: 与 model_gateway._route_remote 是同一 4 行——跨 Context 不共享，各自持有避免反向依赖。
    """
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    return secrets.randbelow(100) < percent


def build_knowledge_search_port(session: AsyncSession) -> _RoutedKnowledgeSearchPort:
    """选择器（Phase 2 唯一切换点）：mode=remote 且配了地址时按 canary 抽样路由 Remote / Local。

    默认 local（percent=0 或 mode=local，无服务时安全）；回滚=percent 归 0。
    远程分支忽略 session（可见性经请求体传递）。
    ponytail: 不包 Route-A 兜底端口——唯一消费方 CurrentKnowledgeAugmentationAdapter.augment
    已 try/except 降级为无增强；检索失败已优雅处理，再加一层是重复。有多消费方时再抽兜底端口。
    """
    settings = get_settings()
    if (
        settings.knowledge_search_mode == "remote"
        and settings.knowledge_gateway_url
        and _route_remote(settings.knowledge_gateway_canary_percent)
    ):
        return build_remote_knowledge_search_port()
    return build_local_knowledge_search_port(session)
