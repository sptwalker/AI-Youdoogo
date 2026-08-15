"""Request-scoped SQLAlchemy Unit of Work for Time Management（暴露三仓储）。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.time_management.infrastructure.sqlalchemy_repository import (
    SQLAlchemyFocusSessionRepository,
    SQLAlchemyScheduleRepository,
    SQLAlchemyTimeLogRepository,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyTimeManagementUnitOfWork(SessionUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._schedules = SQLAlchemyScheduleRepository(session)
        self._focus_sessions = SQLAlchemyFocusSessionRepository(session)
        self._time_logs = SQLAlchemyTimeLogRepository(session)

    @property
    def schedules(self) -> SQLAlchemyScheduleRepository:
        return self._schedules

    @property
    def focus_sessions(self) -> SQLAlchemyFocusSessionRepository:
        return self._focus_sessions

    @property
    def time_logs(self) -> SQLAlchemyTimeLogRepository:
        return self._time_logs
