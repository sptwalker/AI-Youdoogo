"""Request-scoped Time Management composition。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.time_management.application.use_cases import (
    TimeManagementApplication,
)
from app.contexts.business.time_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyTimeManagementUnitOfWork,
)
from app.platform.deterministic import SystemClock, UUIDIdentifier


def build_time_management_application(session: AsyncSession) -> TimeManagementApplication:
    return TimeManagementApplication(
        uow_factory=lambda: SQLAlchemyTimeManagementUnitOfWork(session),
        clock=SystemClock(),
        identifiers=UUIDIdentifier(),
    )
