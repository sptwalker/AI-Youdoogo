"""Unit of work translating database failures at the Identity boundary."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.identity.application.errors import IdentityWriteConflict
from app.contexts.foundations.identity.application.ports import (
    IdentityRepository,
    SourceChangePort,
)
from app.contexts.foundations.identity.infrastructure.adapters import (
    SQLAlchemySourceChangeAdapter,
)
from app.contexts.foundations.identity.infrastructure.sqlalchemy_repository import (
    SQLAlchemyIdentityRepository,
)
from app.platform.database.unit_of_work import IntegrityTranslatingUnitOfWork


class SQLAlchemyIdentityUnitOfWork(IntegrityTranslatingUnitOfWork):
    """Use the request session; the application owns only its transaction."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, write_conflict=IdentityWriteConflict)
        self._identities = SQLAlchemyIdentityRepository(session)
        self._source_changes = SQLAlchemySourceChangeAdapter(session)

    @property
    def identities(self) -> IdentityRepository:
        return self._identities

    @property
    def source_changes(self) -> SourceChangePort:
        return self._source_changes
