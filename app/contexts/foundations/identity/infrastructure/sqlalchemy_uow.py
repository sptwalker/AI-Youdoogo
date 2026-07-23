"""Unit of work translating database failures at the Identity boundary."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.identity.application.errors import IdentityWriteConflict
from app.contexts.foundations.identity.application.ports import (
    IdentityRepository,
    IdentityUnitOfWork,
    SourceChangePort,
)
from app.contexts.foundations.identity.infrastructure.adapters import (
    SQLAlchemySourceChangeAdapter,
)
from app.contexts.foundations.identity.infrastructure.sqlalchemy_repository import (
    SQLAlchemyIdentityRepository,
)


class SQLAlchemyIdentityUnitOfWork(IdentityUnitOfWork):
    """Use the request session; the application owns only its transaction."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._identities = SQLAlchemyIdentityRepository(session)
        self._source_changes = SQLAlchemySourceChangeAdapter(session)

    @property
    def identities(self) -> IdentityRepository:
        return self._identities

    @property
    def source_changes(self) -> SourceChangePort:
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

    async def commit(self) -> None:
        try:
            await self._session.commit()
        except IntegrityError as exc:
            await self._session.rollback()
            raise IdentityWriteConflict() from exc

    async def flush(self) -> None:
        try:
            await self._session.flush()
        except IntegrityError as exc:
            await self._session.rollback()
            raise IdentityWriteConflict() from exc

    async def rollback(self) -> None:
        await self._session.rollback()
