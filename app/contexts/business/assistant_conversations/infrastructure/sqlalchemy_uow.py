"""SQLAlchemy Unit of Work for Assistant Conversations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.assistant_conversations.infrastructure.sqlalchemy_repository import (
    SQLAlchemyConversationRepository,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyConversationUnitOfWork(SessionUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._messages = SQLAlchemyConversationRepository(session)

    @property
    def messages(self) -> SQLAlchemyConversationRepository:
        return self._messages

    def _prepare_for_use(self) -> None:
        self._messages = SQLAlchemyConversationRepository(self._session)
