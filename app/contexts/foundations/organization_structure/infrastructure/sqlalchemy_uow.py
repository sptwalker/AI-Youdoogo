"""Organization Structure unit of work."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.organization_structure.application.errors import (
    OrganizationWriteConflict,
)
from app.contexts.foundations.organization_structure.application.ports import (
    DepartmentRepository,
    OrganizationSourceChangePort,
    OrganizationUnitOfWork,
)
from app.contexts.foundations.organization_structure.infrastructure.adapters import (
    OrganizationSourceChangeAdapter,
)
from app.contexts.foundations.organization_structure.infrastructure.sqlalchemy_repository import (
    SQLAlchemyDepartmentRepository,
)


class SQLAlchemyOrganizationUnitOfWork(OrganizationUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._departments = SQLAlchemyDepartmentRepository(session)
        self._source_changes = OrganizationSourceChangeAdapter(session)

    @property
    def departments(self) -> DepartmentRepository:
        return self._departments

    @property
    def source_changes(self) -> OrganizationSourceChangePort:
        return self._source_changes

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise OrganizationWriteConflict() from exc

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise OrganizationWriteConflict() from exc

    async def rollback(self) -> None:
        await self._session.rollback()
