"""SQLAlchemy unit of work for explicit resource grants."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.access_control.application.ports import (
    AccessControlUnitOfWork,
    GrantRepository,
)
from app.contexts.foundations.access_control.infrastructure.sqlalchemy_repository import (
    SQLAlchemyGrantRepository,
)


class SQLAlchemyAccessControlUnitOfWork(AccessControlUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._grants = SQLAlchemyGrantRepository(session)

    @property
    def grants(self) -> GrantRepository:
        return self._grants

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

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
