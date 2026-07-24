"""Reusable transaction lifecycle for caller-owned SQLAlchemy sessions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

WriteConflictFactory = Callable[[], Exception]
SessionWrite = Callable[[], Awaitable[None]]


class SessionUnitOfWork:
    """Own transaction control for a caller-owned SQLAlchemy session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def __aenter__(self) -> Self:
        self._prepare_for_use()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        if exc_type is not None:
            await self.rollback()

    async def commit(self) -> None:
        await self._session.commit()

    async def flush(self) -> None:
        await self._session.flush()

    async def rollback(self) -> None:
        await self._session.rollback()

    def _prepare_for_use(self) -> None:
        """Refresh request-scoped collaborators when a context requires it."""


class IntegrityTranslatingUnitOfWork(SessionUnitOfWork):
    """Translate database integrity failures at a context boundary."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        write_conflict: WriteConflictFactory,
    ) -> None:
        super().__init__(session)
        self._write_conflict = write_conflict

    async def commit(self) -> None:
        await self._write(self._session.commit)

    async def flush(self) -> None:
        await self._write(self._session.flush)

    async def _write(self, action: SessionWrite) -> None:
        try:
            await action()
        except IntegrityError as exc:
            await self.rollback()
            raise self._write_conflict() from exc
