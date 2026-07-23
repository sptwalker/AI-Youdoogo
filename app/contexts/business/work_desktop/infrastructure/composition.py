"""Request-scoped Work Desktop composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.work_desktop.application.use_cases import (
    WorkDesktopApplication,
)
from app.contexts.business.work_desktop.infrastructure.adapters import (
    KnowledgeObjectStorageAdapter,
    PublishedChannelCounterAdapter,
    PublishedCollaborationQueueAdapter,
    PublishedIdentityDirectoryAdapter,
    PublishedKnowledgeCounterAdapter,
    PublishedProposalQueueAdapter,
    SQLAlchemyDeliverableInboxAdapter,
    SQLAlchemyResolutionQueueAdapter,
    SQLAlchemyTaskDashboardAdapter,
)


def build_work_desktop_application(session: AsyncSession) -> WorkDesktopApplication:
    return WorkDesktopApplication(
        tasks=SQLAlchemyTaskDashboardAdapter(session),
        proposals=PublishedProposalQueueAdapter(session),
        resolutions=SQLAlchemyResolutionQueueAdapter(session),
        collaborations=PublishedCollaborationQueueAdapter(session),
        channels=PublishedChannelCounterAdapter(session),
        knowledge=PublishedKnowledgeCounterAdapter(session),
        identities=PublishedIdentityDirectoryAdapter(session),
        deliverables=SQLAlchemyDeliverableInboxAdapter(session),
        storage=KnowledgeObjectStorageAdapter(),
    )
