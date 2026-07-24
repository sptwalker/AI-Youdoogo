"""SQLAlchemy unit of work for explicit resource grants."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.access_control.application.ports import (
    AccessControlUnitOfWork,
    GrantRepository,
)
from app.contexts.foundations.access_control.infrastructure.sqlalchemy_repository import (
    SQLAlchemyGrantRepository,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyAccessControlUnitOfWork(SessionUnitOfWork, AccessControlUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._grants = SQLAlchemyGrantRepository(session)

    @property
    def grants(self) -> GrantRepository:
        return self._grants
