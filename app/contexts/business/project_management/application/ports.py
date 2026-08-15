"""Project Management 应用层端口：仓储、事务、时钟、标识符（结构化 Protocol，便于 Fake 测试）。"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from typing import Protocol, Self

from app.contexts.business.project_management.domain.models import Project


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...


class ProjectRepository(Protocol):
    async def add(self, project: Project) -> None: ...

    async def get(self, project_id: uuid.UUID) -> Project | None: ...

    async def save(self, project: Project) -> None: ...

    async def list_for_owner(
        self, *, owner_id: uuid.UUID, status: str | None, limit: int
    ) -> tuple[Project, ...]: ...


class ProjectUnitOfWork(Protocol):
    @property
    def projects(self) -> ProjectRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


ProjectUnitOfWorkFactory = Callable[[], ProjectUnitOfWork]
