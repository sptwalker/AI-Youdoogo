"""Project Management 用例与事务归属。

行级隔离铁律：所有读写按 owner_id 归属；命中他人项目一律当作不存在（ResourceNotFound）。
"""

from __future__ import annotations

import uuid

from app.contexts.business.project_management.application.contracts import (
    CreateProjectCommand,
    ListProjectsQuery,
    ProjectResult,
    UpdateProjectCommand,
)
from app.contexts.business.project_management.application.ports import (
    Clock,
    IdentifierPort,
    ProjectUnitOfWork,
    ProjectUnitOfWorkFactory,
)
from app.contexts.business.project_management.domain.models import Project
from app.contexts.shared_kernel import ResourceNotFound


def _result(project: Project) -> ProjectResult:
    assert project.create_time is not None
    return ProjectResult(
        id=project.id,
        name=project.name,
        owner_id=project.owner_id,
        description=project.description,
        status=project.status,
        department_id=project.department_id,
        archived_at=project.archived_at,
        create_time=project.create_time,
    )


class ProjectApplication:
    def __init__(
        self,
        *,
        uow_factory: ProjectUnitOfWorkFactory,
        clock: Clock,
        identifiers: IdentifierPort,
    ) -> None:
        self._uow_factory = uow_factory
        self._clock = clock
        self._identifiers = identifiers

    async def create(self, command: CreateProjectCommand) -> ProjectResult:
        project = Project.create(
            project_id=self._identifiers.new_id(),
            owner_id=command.owner_id,
            name=command.name,
            description=command.description,
            department_id=command.department_id,
            created_at=self._clock.now(),
        )
        async with self._uow_factory() as uow:
            await uow.projects.add(project)
            await uow.commit()
        return _result(project)

    async def list(self, query: ListProjectsQuery) -> tuple[ProjectResult, ...]:
        async with self._uow_factory() as uow:
            projects = await uow.projects.list_for_owner(
                owner_id=query.owner_id, status=query.status, limit=query.limit
            )
        return tuple(_result(project) for project in projects)

    async def get(self, project_id: uuid.UUID, *, owner_id: uuid.UUID) -> ProjectResult:
        async with self._uow_factory() as uow:
            project = await self._load(uow, project_id, owner_id)
        return _result(project)

    async def update(self, command: UpdateProjectCommand) -> ProjectResult:
        async with self._uow_factory() as uow:
            project = await self._load(uow, command.project_id, command.owner_id)
            if command.name is not None:
                project.rename(command.name)
            if command.description is not None:
                project.set_description(command.description)
            await uow.projects.save(project)
            await uow.commit()
        return _result(project)

    async def archive(self, project_id: uuid.UUID, *, owner_id: uuid.UUID) -> ProjectResult:
        async with self._uow_factory() as uow:
            project = await self._load(uow, project_id, owner_id)
            project.archive(at=self._clock.now())
            await uow.projects.save(project)
            await uow.commit()
        return _result(project)

    @staticmethod
    async def _load(
        uow: ProjectUnitOfWork, project_id: uuid.UUID, owner_id: uuid.UUID
    ) -> Project:
        project = await uow.projects.get(project_id)
        if project is None or project.owner_id != owner_id:
            raise ResourceNotFound("项目不存在")
        return project
