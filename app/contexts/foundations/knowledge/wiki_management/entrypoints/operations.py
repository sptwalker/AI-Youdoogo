"""Request-scoped compatibility operations for Wiki Management."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.wiki_management.application.contracts import (
    CreateKnowledgeBase,
    UpdateKnowledgeBase,
)
from app.contexts.foundations.knowledge.wiki_management.application.use_cases import WikiManagement
from app.contexts.foundations.knowledge.wiki_management.contracts import (
    KnowledgeBaseSnapshot,
    KnowledgeScope,
)
from app.contexts.foundations.knowledge.wiki_management.infrastructure.sqlalchemy import (
    SqlAlchemyWikiUnitOfWork,
)


def _service(session: AsyncSession) -> WikiManagement:
    return WikiManagement(lambda: SqlAlchemyWikiUnitOfWork(session))


async def get_knowledge_base(
    session: AsyncSession, knowledge_base_id: uuid.UUID
) -> KnowledgeBaseSnapshot:
    return await _service(session).get(knowledge_base_id)


async def get_default_knowledge_base(session: AsyncSession) -> KnowledgeBaseSnapshot:
    return await _service(session).get_default()


async def list_knowledge_bases(session: AsyncSession) -> tuple[KnowledgeBaseSnapshot, ...]:
    return await _service(session).list()


async def create_knowledge_base(
    session: AsyncSession,
    *,
    name: str,
    scope: str,
    code: str | None = None,
    department_id: uuid.UUID | None = None,
    owner_agent_id: uuid.UUID | None = None,
    is_confidential: bool = False,
    description: str | None = None,
) -> KnowledgeBaseSnapshot:
    return await _service(session).create(
        CreateKnowledgeBase(
            name=name,
            scope=KnowledgeScope(scope),
            code=code,
            department_id=department_id,
            owner_agent_id=owner_agent_id,
            is_confidential=is_confidential,
            description=description,
        )
    )


async def update_knowledge_base(
    session: AsyncSession,
    knowledge_base_id: uuid.UUID,
    *,
    name: str | None = None,
    is_confidential: bool | None = None,
    description: str | None = None,
    is_active: bool | None = None,
    department_id: uuid.UUID | None = None,
) -> KnowledgeBaseSnapshot:
    return await _service(session).update(
        UpdateKnowledgeBase(
            knowledge_base_id=knowledge_base_id,
            name=name,
            is_confidential=is_confidential,
            description=description,
            is_active=is_active,
            department_id=department_id,
        )
    )


async def delete_knowledge_base(session: AsyncSession, knowledge_base_id: uuid.UUID) -> None:
    await _service(session).delete(knowledge_base_id)
