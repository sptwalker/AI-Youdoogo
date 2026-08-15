"""Request-scoped SQLAlchemy Unit of Work for Project Management。"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.project_management.infrastructure.sqlalchemy_repository import (
    SQLAlchemyProjectRepository,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyProjectUnitOfWork(SessionUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._projects = SQLAlchemyProjectRepository(session)

    @property
    def projects(self) -> SQLAlchemyProjectRepository:
        return self._projects
