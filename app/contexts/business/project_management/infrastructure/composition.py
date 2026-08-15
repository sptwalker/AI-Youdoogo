"""Request-scoped Project Management composition。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.project_management.application.use_cases import (
    ProjectApplication,
)
from app.contexts.business.project_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyProjectUnitOfWork,
)
from app.platform.deterministic import SystemClock, UUIDIdentifier


def build_project_application(session: AsyncSession) -> ProjectApplication:
    return ProjectApplication(
        uow_factory=lambda: SQLAlchemyProjectUnitOfWork(session),
        clock=SystemClock(),
        identifiers=UUIDIdentifier(),
    )
