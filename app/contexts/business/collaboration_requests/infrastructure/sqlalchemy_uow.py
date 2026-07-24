"""SQLAlchemy Unit of Work for Collaboration Requests."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.collaboration_requests.infrastructure.sqlalchemy_repository import (
    SQLAlchemyCollaborationRepository,
)
from app.platform.database.unit_of_work import SessionUnitOfWork


class SQLAlchemyCollaborationUnitOfWork(SessionUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._collaborations = SQLAlchemyCollaborationRepository(session)

    @property
    def collaborations(self) -> SQLAlchemyCollaborationRepository:
        return self._collaborations

    def _prepare_for_use(self) -> None:
        self._collaborations = SQLAlchemyCollaborationRepository(self._session)
