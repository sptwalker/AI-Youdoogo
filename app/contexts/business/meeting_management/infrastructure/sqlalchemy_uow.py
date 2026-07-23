"""Request-scoped SQLAlchemy Unit of Work for Meeting Management."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.meeting_management.infrastructure.sqlalchemy_repository import (
    SQLAlchemyMeetingRepository,
)


class SQLAlchemyMeetingUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._meetings = SQLAlchemyMeetingRepository(session)

    @property
    def meetings(self) -> SQLAlchemyMeetingRepository:
        return self._meetings

    async def __aenter__(self) -> SQLAlchemyMeetingUnitOfWork:
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
