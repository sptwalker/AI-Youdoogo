"""Current published adapters for Agent Execution composition."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.application.knowledge import (
    build_knowledge_block,
)
from app.contexts.foundations.execution.agent_execution.application.prompts import (
    DEFAULT_GLOBAL_PROMPT,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    KnowledgeAugmentation,
    SourceReference,
)
from app.contexts.foundations.governance.system_configuration.public import (
    resolve_configuration,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.contracts import (
    SearchKnowledgeQuery,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.public import search_knowledge
from app.contexts.foundations.knowledge.semantic_catalog.public import term_prompt
from app.contexts.foundations.knowledge.wiki_management.public import (
    agent_visible_knowledge_base_ids,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)

logger = logging.getLogger(__name__)


class CurrentPromptAssemblyAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def build(self, expert: ExpertExecutionSnapshot) -> str:
        configured = await resolve_configuration(
            self._session,
            "agent_global_prompt",
            DEFAULT_GLOBAL_PROMPT,
        )
        return f"{configured}\n\n{expert.prompt_template}{await term_prompt(self._session)}"


class CurrentKnowledgeAugmentationAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def augment(
        self, expert: ExpertExecutionSnapshot, user_message: str
    ) -> KnowledgeAugmentation:
        try:
            knowledge_ids = await agent_visible_knowledge_base_ids(
                self._session,
                department_id=expert.department_id,
                owner_agent_id=expert.expert_id,
            )
            result = await search_knowledge(
                self._session,
                SearchKnowledgeQuery(
                    query=user_message,
                    top_k=5,
                    visible_knowledge_base_ids=tuple(knowledge_ids),
                ),
            )
            if not result.hits:
                return KnowledgeAugmentation(message=user_message)
            return KnowledgeAugmentation(
                message=build_knowledge_block(
                    tuple((hit.content, hit.document_name) for hit in result.hits),
                    user_message,
                ),
                sources=tuple(
                    SourceReference(
                        str(hit.document_id),
                        hit.document_name,
                        hit.chunk_index,
                    )
                    for hit in result.hits
                ),
            )
        except Exception:  # noqa: BLE001 - knowledge failure keeps execution available
            logger.warning("知识库检索注入失败 expert=%s", expert.expert_id, exc_info=True)
            return KnowledgeAugmentation(message=user_message)
