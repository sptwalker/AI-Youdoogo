"""SQLAlchemy Unit of Work for Assistant Conversations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.assistant_conversations.infrastructure.sqlalchemy_repository import (
    SQLAlchemyConversationRepository,
)


class SQLAlchemyConversationUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._messages = SQLAlchemyConversationRepository(session)

    @property
    def messages(self) -> SQLAlchemyConversationRepository:
        return self._messages

    async def __aenter__(self) -> SQLAlchemyConversationUnitOfWork:
        self._messages = SQLAlchemyConversationRepository(self._session)
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

    async def rollback(self) -> None:
        await self._session.rollback()
