"""Project Management 请求级入口：装配 Application 并执行单个用例（薄封装）。"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.project_management.application.contracts import (
    CreateProjectCommand,
    ListProjectsQuery,
    ProjectResult,
    UpdateProjectCommand,
)
from app.contexts.business.project_management.infrastructure.composition import (
    build_project_application,
)


async def create_project(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    name: str,
    description: str | None = None,
    department_id: uuid.UUID | None = None,
) -> ProjectResult:
    return await build_project_application(session).create(
        CreateProjectCommand(
            owner_id=owner_id,
            name=name,
            description=description,
            department_id=department_id,
        )
    )


async def list_projects(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    status: str | None = None,
    limit: int = 100,
) -> tuple[ProjectResult, ...]:
    return await build_project_application(session).list(
        ListProjectsQuery(owner_id=owner_id, status=status, limit=limit)
    )


async def get_project(
    session: AsyncSession, project_id: uuid.UUID, *, owner_id: uuid.UUID
) -> ProjectResult:
    return await build_project_application(session).get(project_id, owner_id=owner_id)


async def update_project(
    session: AsyncSession,
    project_id: uuid.UUID,
    *,
    owner_id: uuid.UUID,
    name: str | None = None,
    description: str | None = None,
) -> ProjectResult:
    return await build_project_application(session).update(
        UpdateProjectCommand(
            project_id=project_id,
            owner_id=owner_id,
            name=name,
            description=description,
        )
    )


async def archive_project(
    session: AsyncSession, project_id: uuid.UUID, *, owner_id: uuid.UUID
) -> ProjectResult:
    return await build_project_application(session).archive(project_id, owner_id=owner_id)
