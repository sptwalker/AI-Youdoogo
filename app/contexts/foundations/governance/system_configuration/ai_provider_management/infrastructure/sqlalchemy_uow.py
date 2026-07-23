"""SQLAlchemy Unit of Work for AI Provider Management."""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy.ext.asyncio import AsyncSession

from ..application.ports import ProviderRepositoryPort
from .sqlalchemy_repository import SQLAlchemyProviderRepository


class SQLAlchemyProviderUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._providers = SQLAlchemyProviderRepository(session)

    @property
    def providers(self) -> ProviderRepositoryPort:
        return self._providers

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
        await self._session.flush()

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()
