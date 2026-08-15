"""SQLAlchemy mapper 与仓储：Project ORM ↔ 领域对象。project 表唯一持久化 writer。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.project_management.domain.models import Project
from app.models.project import Project as ProjectRow


def _from_row(row: ProjectRow) -> Project:
    return Project(
        id=row.id,
        name=row.name,
        owner_id=row.owner_id,
        description=row.description,
        status=row.status,
        department_id=row.department_id,
        archived_at=row.archived_at,
        create_time=row.create_time,
    )


class SQLAlchemyProjectRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, project: Project) -> None:
        self._session.add(
            ProjectRow(
                id=project.id,
                name=project.name,
                owner_id=project.owner_id,
                description=project.description,
                status=project.status,
                department_id=project.department_id,
                archived_at=project.archived_at,
                create_time=project.create_time,
            )
        )
        await self._session.flush()

    async def get(self, project_id: uuid.UUID) -> Project | None:
        row = await self._session.get(ProjectRow, project_id)
        if row is None or row.is_delete:
            return None
        return _from_row(row)

    async def save(self, project: Project) -> None:
        row = await self._session.get(ProjectRow, project.id)
        if row is None or row.is_delete:
            return
        row.name = project.name
        row.description = project.description
        row.status = project.status
        row.department_id = project.department_id
        row.archived_at = project.archived_at
        await self._session.flush()

    async def list_for_owner(
        self, *, owner_id: uuid.UUID, status: str | None, limit: int
    ) -> tuple[Project, ...]:
        statement = select(ProjectRow).where(
            ProjectRow.is_delete.is_(False), ProjectRow.owner_id == owner_id
        )
        if status:
            statement = statement.where(ProjectRow.status == status)
        rows = (
            await self._session.execute(
                statement.order_by(ProjectRow.create_time.desc()).limit(limit)
            )
        ).scalars()
        return tuple(_from_row(row) for row in rows)
