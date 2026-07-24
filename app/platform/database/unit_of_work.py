"""Reusable transaction lifecycle for caller-owned SQLAlchemy sessions."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from types import TracebackType
from typing import Self

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

WriteConflictFactory = Callable[[], Exception]
SessionWrite = Callable[[], Awaitable[None]]


class IntegrityTranslatingUnitOfWork:
    """Own transaction control and translate database integrity failures once."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        write_conflict: WriteConflictFactory,
    ) -> None:
        self._session = session
        self._write_conflict = write_conflict

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
        await self._write(self._session.commit)

    async def flush(self) -> None:
        await self._write(self._session.flush)

    async def rollback(self) -> None:
        await self._session.rollback()

    async def _write(self, action: SessionWrite) -> None:
        try:
            await action()
        except IntegrityError as exc:
            await self.rollback()
            raise self._write_conflict() from exc
