"""SQLAlchemy Unit of Work for AI Provider Management."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.database.unit_of_work import SessionUnitOfWork

from ..application.ports import ProviderRepositoryPort
from .sqlalchemy_repository import SQLAlchemyProviderRepository


class SQLAlchemyProviderUnitOfWork(SessionUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._providers = SQLAlchemyProviderRepository(session)

    @property
    def providers(self) -> ProviderRepositoryPort:
        return self._providers
