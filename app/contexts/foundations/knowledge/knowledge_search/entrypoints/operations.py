"""Entrypoint 网关：把 agent 可见知识库范围内的混合检索暴露给能力层。

复用 ``knowledge_retrieval.public.build_knowledge_search_port`` 选择器（local/remote 对等，
canary 由该选择器内部决定），检索范围沿用 ``wiki_management.agent_visible_knowledge_base_ids``
既有权限推导（按部门 + 归属 agent），不新增权限面；跨 Context 只经 public 门面、绝不直连 gateway。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import AgentSubject
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    KnowledgeHit,
    SearchKnowledgeQuery,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.public import (
    build_knowledge_search_port,
)
from app.contexts.foundations.knowledge.wiki_management.public import (
    agent_visible_knowledge_base_ids,
)


async def search_visible(
    session: AsyncSession, subject: AgentSubject, query: str, top_k: int = 5
) -> tuple[KnowledgeHit, ...]:
    """在 subject 可见知识库范围内做一次混合检索，返回命中片段（无命中即空元组）。

    ``subject.expert_id`` 即归属 agent（个人库 owner），``department_id`` 决定公司/部门库可见性。
    """
    kb_ids = await agent_visible_knowledge_base_ids(
        session,
        department_id=subject.department_id,
        owner_agent_id=subject.expert_id,
    )
    port = build_knowledge_search_port(session)
    result = await port.search(
        SearchKnowledgeQuery(
            query=query,
            top_k=top_k,
            visible_knowledge_base_ids=tuple(kb_ids),
        )
    )
    return result.hits
