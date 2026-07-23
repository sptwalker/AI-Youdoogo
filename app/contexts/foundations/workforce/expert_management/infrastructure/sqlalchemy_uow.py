"""Expert Management unit of work over the request session."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.application.errors import (
    ExpertWriteConflict,
)
from app.contexts.foundations.workforce.expert_management.application.management_ports import (
    ExpertRepository,
    ExpertSourceChangePort,
    ExpertUnitOfWork,
)
from app.contexts.foundations.workforce.expert_management.infrastructure import (
    sqlalchemy_repository,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.adapters import (
    ExpertSourceChangeAdapter,
)


class SQLAlchemyExpertUnitOfWork(ExpertUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._experts = sqlalchemy_repository.SQLAlchemyExpertRepository(session)
        self._source_changes = ExpertSourceChangeAdapter(session)

    @property
    def experts(self) -> ExpertRepository:
        return self._experts

    @property
    def source_changes(self) -> ExpertSourceChangePort:
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
            raise ExpertWriteConflict() from exc

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise ExpertWriteConflict() from exc

    async def rollback(self) -> None:
        await self._session.rollback()
