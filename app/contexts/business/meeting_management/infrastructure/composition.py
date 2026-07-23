"""Request-scoped Meeting Management composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.meeting_management.application.use_cases import (
    MeetingApplication,
)
from app.contexts.business.meeting_management.infrastructure.adapters import (
    AccessControlMeetingVisibilityPolicy,
    LegacyMeetingAdvisoryAdapter,
    SystemClock,
    TaskManagementCreationAdapter,
    UUIDIdentifier,
)
from app.contexts.business.meeting_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyMeetingUnitOfWork,
)


def build_meeting_application(session: AsyncSession) -> MeetingApplication:
    return MeetingApplication(
        uow_factory=lambda: SQLAlchemyMeetingUnitOfWork(session),
        advisory_port=LegacyMeetingAdvisoryAdapter(session),
        task_port=TaskManagementCreationAdapter(session),
        visibility_policy=AccessControlMeetingVisibilityPolicy(),
        clock=SystemClock(),
        identifiers=UUIDIdentifier(),
    )
