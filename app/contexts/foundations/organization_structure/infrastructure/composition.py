"""Request-scoped Organization Structure composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.organization_structure.application.use_cases import (
    OrganizationStructureApplication,
)
from app.contexts.foundations.organization_structure.infrastructure.adapters import (
    FeishuOrganizationDirectoryAdapter,
    PublishedExpertManagementAdapter,
    PublishedGroupMessagingAdapter,
    PublishedIdentityDirectoryAdapter,
    PublishedIdentitySyncAdapter,
)
from app.contexts.foundations.organization_structure.infrastructure.sqlalchemy_uow import (
    SQLAlchemyOrganizationUnitOfWork,
)
from app.platform.deterministic import SystemClock, UUIDIdentifier


def build_organization_structure_application(
    session: AsyncSession,
) -> OrganizationStructureApplication:
    return OrganizationStructureApplication(
        uow_factory=lambda: SQLAlchemyOrganizationUnitOfWork(session),
        experts=PublishedExpertManagementAdapter(session),
        identities=PublishedIdentityDirectoryAdapter(session),
        external_directory=FeishuOrganizationDirectoryAdapter(),
        external_identities=PublishedIdentitySyncAdapter(session),
        discussions=PublishedGroupMessagingAdapter(session),
        identifiers=UUIDIdentifier(),
        clock=SystemClock(),
    )
