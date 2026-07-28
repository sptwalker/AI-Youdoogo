"""Request-scoped Expert Management composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.application.use_cases import (
    ExpertManagementApplication,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.local_adapter import (
    LocalExpertManagementAdapter,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertRosterQuery,
    SQLAlchemyExpertSnapshotQuery,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyExpertUnitOfWork,
)
from app.platform.deterministic import SystemClock, UUIDIdentifier


def build_expert_management_application(session: AsyncSession) -> ExpertManagementApplication:
    return ExpertManagementApplication(
        uow_factory=lambda: SQLAlchemyExpertUnitOfWork(session),
        roster=SQLAlchemyExpertRosterQuery(session),
        identifiers=UUIDIdentifier(),
        clock=SystemClock(),
    )


def build_local_expert_management(session: AsyncSession) -> LocalExpertManagementAdapter:
    """Bind the stable Expert object API to the current request-scoped persistence."""
    roster = SQLAlchemyExpertRosterQuery(session)
    application = ExpertManagementApplication(
        uow_factory=lambda: SQLAlchemyExpertUnitOfWork(session),
        roster=roster,
        identifiers=UUIDIdentifier(),
        clock=SystemClock(),
    )
    return LocalExpertManagementAdapter(
        application=application,
        roster=roster,
        snapshots=SQLAlchemyExpertSnapshotQuery(session),
    )
