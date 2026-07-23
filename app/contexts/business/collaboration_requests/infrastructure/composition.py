"""Request-scoped compatibility composition for Collaboration Requests."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.collaboration_requests.application.use_cases import (
    CollaborationRequestsApplication,
)
from app.contexts.business.collaboration_requests.infrastructure.adapters import (
    LegacyAuditAdapter,
    OrganizationReviewScopeAdapter,
    SystemClock,
    UUIDIdentifier,
)
from app.contexts.business.collaboration_requests.infrastructure.sqlalchemy_uow import (
    SQLAlchemyCollaborationUnitOfWork,
)


def build_collaboration_requests_application(
    session: AsyncSession,
) -> CollaborationRequestsApplication:
    return CollaborationRequestsApplication(
        uow_factory=lambda: SQLAlchemyCollaborationUnitOfWork(session),
        review_scope=OrganizationReviewScopeAdapter(session),
        audit_port=LegacyAuditAdapter(session),
        clock=SystemClock(),
        identifiers=UUIDIdentifier(),
    )
