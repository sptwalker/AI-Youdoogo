"""SQLAlchemy Unit of Work for Group Messaging."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.group_messaging.infrastructure.sqlalchemy_repository import (
    SQLAlchemyGroupMessagingRepository,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyGroupMessagingUnitOfWork(SessionUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._messages = SQLAlchemyGroupMessagingRepository(session)

    @property
    def messages(self) -> SQLAlchemyGroupMessagingRepository:
        return self._messages

    def _prepare_for_use(self) -> None:
        self._messages = SQLAlchemyGroupMessagingRepository(self._session)
