"""Request-scoped composition for the Proposal slice during bootstrap migration."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.proposal_management.application.use_cases import ProposalApplication
from app.contexts.business.proposal_management.infrastructure.adapters import (
    CurrentProposalVisibilityPolicy,
    LegacyAuditAdapter,
    LegacyExpertResearchAdapter,
    LegacyTaskCreationAdapter,
    SystemClock,
    UUIDIdentifier,
)
from app.contexts.business.proposal_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyProposalUnitOfWork,
)


def build_proposal_application(session: AsyncSession) -> ProposalApplication:
    """Build one request-scoped Application boundary from the existing DB session."""
    return ProposalApplication(
        uow_factory=lambda: SQLAlchemyProposalUnitOfWork(session),
        research_port=LegacyExpertResearchAdapter(session),
        task_port=LegacyTaskCreationAdapter(session),
        visibility_policy=CurrentProposalVisibilityPolicy(),
        audit_port=LegacyAuditAdapter(session),
        clock=SystemClock(),
        identifiers=UUIDIdentifier(),
    )
