"""Request-scoped compatibility composition for Collaboration Requests."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.collaboration_requests.application.use_cases import (
    CollaborationRequestsApplication,
)
from app.contexts.business.collaboration_requests.infrastructure.adapters import (
    OrganizationReviewScopeAdapter,
    PublishedAuditAdapter,
)
from app.contexts.business.collaboration_requests.infrastructure.sqlalchemy_uow import (
    SQLAlchemyCollaborationUnitOfWork,
)
from app.platform.deterministic import SystemClock, UUIDIdentifier


def build_collaboration_requests_application(
    session: AsyncSession,
) -> CollaborationRequestsApplication:
    return CollaborationRequestsApplication(
        uow_factory=lambda: SQLAlchemyCollaborationUnitOfWork(session),
        review_scope=OrganizationReviewScopeAdapter(session),
        audit_port=PublishedAuditAdapter(session),
        clock=SystemClock(),
        identifiers=UUIDIdentifier(),
    )
