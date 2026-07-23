"""SQL visibility queries owned by Wiki Management."""

from __future__ import annotations

import uuid

from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    SCOPE_COMPANY,
    SCOPE_DEPARTMENT,
    SCOPE_PERSONAL,
    KnowledgeBase,
)
from app.models.system import SysDepartment


async def department_path(session: AsyncSession, department_id: uuid.UUID | None) -> str:
    if department_id is None:
        return ""
    department = await session.get(SysDepartment, department_id)
    return department.path if department and not department.is_delete else ""


def ancestor_ids(path: str) -> list[uuid.UUID]:
    return [uuid.UUID(segment) for segment in path.strip("/").split("/") if segment]


async def ancestor_department_ids(
    session: AsyncSession, department_id: uuid.UUID | None
) -> list[uuid.UUID]:
    return ancestor_ids(await department_path(session, department_id))


async def visible_knowledge_base_ids(
    session: AsyncSession,
    *,
    department_id: uuid.UUID | None,
    owner_agent_id: uuid.UUID | None = None,
    is_admin: bool = False,
    extra_knowledge_base_ids: list[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    if is_admin:
        statement = select(KnowledgeBase.id).where(
            KnowledgeBase.is_active.is_(True),
            KnowledgeBase.is_delete.is_(False),
        )
        return list((await session.execute(statement)).scalars())

    ancestors = ancestor_ids(await department_path(session, department_id))
    public_condition = KnowledgeBase.is_confidential.is_(False)
    confidential_condition = KnowledgeBase.is_confidential.is_(True) & (
        KnowledgeBase.department_id.in_(ancestors) if ancestors else false()
    )
    personal_condition = (
        (KnowledgeBase.scope == SCOPE_PERSONAL) & (KnowledgeBase.owner_agent_id == owner_agent_id)
        if owner_agent_id is not None
        else false()
    )
    statement = select(KnowledgeBase.id).where(
        KnowledgeBase.is_active.is_(True),
        KnowledgeBase.is_delete.is_(False),
        or_(
            public_condition & (KnowledgeBase.scope != SCOPE_PERSONAL),
            confidential_condition,
            personal_condition,
        ),
    )
    identifiers = list((await session.execute(statement)).scalars())
    if extra_knowledge_base_ids:
        identifiers = list({*identifiers, *extra_knowledge_base_ids})
    return identifiers


async def agent_visible_knowledge_base_ids(
    session: AsyncSession,
    *,
    department_id: uuid.UUID | None,
    owner_agent_id: uuid.UUID | None = None,
) -> list[uuid.UUID]:
    ancestors = await ancestor_department_ids(session, department_id)
    conditions = [KnowledgeBase.scope == SCOPE_COMPANY]
    if ancestors:
        conditions.append(
            (KnowledgeBase.scope == SCOPE_DEPARTMENT) & KnowledgeBase.department_id.in_(ancestors)
        )
    if owner_agent_id is not None:
        conditions.append(
            (KnowledgeBase.scope == SCOPE_PERSONAL)
            & (KnowledgeBase.owner_agent_id == owner_agent_id)
        )
    statement = select(KnowledgeBase.id).where(
        KnowledgeBase.is_active.is_(True),
        KnowledgeBase.is_delete.is_(False),
        or_(*conditions),
    )
    return list((await session.execute(statement)).scalars())
