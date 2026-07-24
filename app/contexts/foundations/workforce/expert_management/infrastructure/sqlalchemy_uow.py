"""Expert Management unit of work over the request session."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.application.errors import (
    ExpertWriteConflict,
)
from app.contexts.foundations.workforce.expert_management.application.management_ports import (
    ExpertRepository,
    ExpertSourceChangePort,
)
from app.contexts.foundations.workforce.expert_management.infrastructure import (
    sqlalchemy_repository,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.adapters import (
    ExpertSourceChangeAdapter,
)
from app.platform.database.unit_of_work import IntegrityTranslatingUnitOfWork


class SQLAlchemyExpertUnitOfWork(IntegrityTranslatingUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, write_conflict=ExpertWriteConflict)
        self._experts = sqlalchemy_repository.SQLAlchemyExpertRepository(session)
        self._source_changes = ExpertSourceChangeAdapter(session)

    @property
    def experts(self) -> ExpertRepository:
        return self._experts

    @property
    def source_changes(self) -> ExpertSourceChangePort:
        return self._source_changes
