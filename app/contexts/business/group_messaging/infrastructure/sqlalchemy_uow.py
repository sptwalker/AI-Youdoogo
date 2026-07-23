"""SQLAlchemy Unit of Work for Group Messaging."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.group_messaging.infrastructure.sqlalchemy_repository import (
    SQLAlchemyGroupMessagingRepository,
)


class SQLAlchemyGroupMessagingUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._messages = SQLAlchemyGroupMessagingRepository(session)

    @property
    def messages(self) -> SQLAlchemyGroupMessagingRepository:
        return self._messages

    async def __aenter__(self) -> SQLAlchemyGroupMessagingUnitOfWork:
        self._messages = SQLAlchemyGroupMessagingRepository(self._session)
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
