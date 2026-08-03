"""Request-scoped Access Control composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.access_control.application.use_cases import (
    AccessControlApplication,
)
from app.contexts.foundations.access_control.infrastructure.adapters import (
    LegacyDepartmentHierarchyAdapter,
    LegacyKnowledgeVisibilityAdapter,
)
from app.contexts.foundations.access_control.infrastructure.sqlalchemy_uow import (
    SQLAlchemyAccessControlUnitOfWork,
)
from app.platform.deterministic import SystemClock, UUIDIdentifier


def build_access_control_application(session: AsyncSession) -> AccessControlApplication:
    return AccessControlApplication(
        uow_factory=lambda: SQLAlchemyAccessControlUnitOfWork(session),
        departments=LegacyDepartmentHierarchyAdapter(session),
        knowledge_visibility=LegacyKnowledgeVisibilityAdapter(session),
        identifiers=UUIDIdentifier(),
        clock=SystemClock(),
    )
