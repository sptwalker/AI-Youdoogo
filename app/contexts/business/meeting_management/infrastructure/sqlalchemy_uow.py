"""Request-scoped SQLAlchemy Unit of Work for Meeting Management."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.meeting_management.infrastructure.sqlalchemy_repository import (
    SQLAlchemyMeetingRepository,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyMeetingUnitOfWork(SessionUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._meetings = SQLAlchemyMeetingRepository(session)

    @property
    def meetings(self) -> SQLAlchemyMeetingRepository:
        return self._meetings
