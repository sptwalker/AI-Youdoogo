"""Outer adapters from current prompt/knowledge facilities to clean Agent ports."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

import app.agents.skill_registry as skill_registry
from app.contexts.foundations.execution.agent_execution.application.knowledge import (
    build_knowledge_block,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    KnowledgeAugmentation,
    SourceReference,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    SearchKnowledgeQuery,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.public import (
    search_knowledge,
)
from app.contexts.foundations.knowledge.semantic_catalog.public import (
    term_prompt,
)
from app.contexts.foundations.knowledge.wiki_management.public import (
    agent_visible_knowledge_base_ids,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.models.agent import AgentRole
from app.services import config_service

logger = logging.getLogger(__name__)


class LegacyPromptAssemblyAdapter:
    """Preserve global, expert, capability, and semantic prompt ordering."""

    def __init__(
        self,
        session: AsyncSession,
        role_record: AgentRole,
        default_global_prompt: str,
    ) -> None:
        self._session = session
        self._role = role_record
        self._default = default_global_prompt

    async def build(self, expert: ExpertExecutionSnapshot) -> str:
        try:
            global_prompt = await config_service.resolve(
                self._session, "agent_global_prompt", self._default
            )
        except Exception:  # noqa: BLE001 - configuration failure keeps the built-in red line
            logger.warning("读取 agent_global_prompt 失败，回退内置默认", exc_info=True)
            global_prompt = self._default
        return (
            f"{global_prompt}\n\n{expert.prompt_template}"
            f"{await skill_registry.prompt_sections(self._session, self._role)}"
            f"{await term_prompt(self._session)}"
        )


class LegacyKnowledgeAugmentationAdapter:
    """Translate current retrieval hits to immutable source references."""

    def __init__(self, session: AsyncSession, role_record: AgentRole) -> None:
        self._session = session
        self._role = role_record

    async def augment(
        self, expert: ExpertExecutionSnapshot, user_message: str
    ) -> KnowledgeAugmentation:
        try:
            kb_ids = await agent_visible_knowledge_base_ids(
                self._session,
                department_id=expert.department_id,
                owner_agent_id=expert.expert_id,
            )
            result = await search_knowledge(
                self._session,
                SearchKnowledgeQuery(
                    query=user_message,
                    top_k=5,
                    visible_knowledge_base_ids=tuple(kb_ids),
                ),
            )
            hits = result.hits
            if not hits:
                return KnowledgeAugmentation(message=user_message)
            sources = tuple(
                SourceReference(str(hit.document_id), hit.document_name, hit.chunk_index)
                for hit in hits
            )
            message = build_knowledge_block(
                tuple((hit.content, hit.document_name) for hit in hits),
                user_message,
            )
            return KnowledgeAugmentation(message=message, sources=sources)
        except Exception:  # noqa: BLE001 - retrieval failure must not block execution
            logger.warning(
                "知识库检索注入失败，改为无资料执行 role=%s",
                self._role.name,
                exc_info=True,
            )
            return KnowledgeAugmentation(message=user_message)
