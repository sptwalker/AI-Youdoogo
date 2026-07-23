"""Request-scoped Expert Management composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.application.use_cases import (
    ExpertManagementApplication,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.adapters import (
    SystemClock,
    UUIDIdentifier,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertRosterQuery,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyExpertUnitOfWork,
)


def build_expert_management_application(session: AsyncSession) -> ExpertManagementApplication:
    return ExpertManagementApplication(
        uow_factory=lambda: SQLAlchemyExpertUnitOfWork(session),
        roster=SQLAlchemyExpertRosterQuery(session),
        identifiers=UUIDIdentifier(),
        clock=SystemClock(),
    )
