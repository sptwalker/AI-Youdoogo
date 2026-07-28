"""Request-scoped composition for the Proposal slice during bootstrap migration."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.proposal_management.application.use_cases import ProposalApplication
from app.contexts.business.proposal_management.infrastructure.adapters import (
    CurrentProposalVisibilityPolicy,
    LegacyExpertResearchAdapter,
    ProposalIdentifier,
    PublishedAuditAdapter,
    PublishedTaskCreationAdapter,
)
from app.contexts.business.proposal_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyProposalUnitOfWork,
)
from app.platform.deterministic import SystemClock


def build_proposal_application(session: AsyncSession) -> ProposalApplication:
    """Build one request-scoped Application boundary from the existing DB session."""
    return ProposalApplication(
        uow_factory=lambda: SQLAlchemyProposalUnitOfWork(session),
        research_port=LegacyExpertResearchAdapter(session),
        task_port=PublishedTaskCreationAdapter(session),
        visibility_policy=CurrentProposalVisibilityPolicy(),
        audit_port=PublishedAuditAdapter(session),
        clock=SystemClock(),
        identifiers=ProposalIdentifier(),
    )
