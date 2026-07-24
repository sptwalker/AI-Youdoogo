"""Organization Structure unit of work."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.organization_structure.application.errors import (
    OrganizationWriteConflict,
)
from app.contexts.foundations.organization_structure.application.ports import (
    DepartmentRepository,
    OrganizationSourceChangePort,
)
from app.contexts.foundations.organization_structure.infrastructure.adapters import (
    OrganizationSourceChangeAdapter,
)
from app.contexts.foundations.organization_structure.infrastructure.sqlalchemy_repository import (
    SQLAlchemyDepartmentRepository,
)
from app.platform.database.unit_of_work import IntegrityTranslatingUnitOfWork


class SQLAlchemyOrganizationUnitOfWork(IntegrityTranslatingUnitOfWork):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, write_conflict=OrganizationWriteConflict)
        self._departments = SQLAlchemyDepartmentRepository(session)
        self._source_changes = OrganizationSourceChangeAdapter(session)

    @property
    def departments(self) -> DepartmentRepository:
        return self._departments

    @property
    def source_changes(self) -> OrganizationSourceChangePort:
        return self._source_changes
