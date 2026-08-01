"""Request-scoped Expert Management composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.application.release_publisher import (
    NoopReleasePublisher,
    ReleasePublisherPort,
)
from app.contexts.foundations.workforce.expert_management.application.use_cases import (
    ExpertManagementApplication,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.adapters import (
    SystemClock,
    UUIDIdentifier,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.release_publisher import (
    HttpReleasePublisher,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertRosterQuery,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_uow import (
    SQLAlchemyExpertUnitOfWork,
)
from app.core.config import get_settings


def _release_publisher() -> ReleasePublisherPort:
    """按 ``expert_execution_mode`` 选发布推送 impl（默认 Noop 不出站，生产逐字不变）。

    推送不看 canary——发布是低频特权写，配了远端就应把快照对齐过去（远端存内存快照供 prepare）。
    """
    settings = get_settings()
    if settings.expert_execution_mode == "remote" and settings.expert_platform_url:
        return HttpReleasePublisher(base_url=settings.expert_platform_url)
    return NoopReleasePublisher()


def build_expert_management_application(session: AsyncSession) -> ExpertManagementApplication:
    return ExpertManagementApplication(
        uow_factory=lambda: SQLAlchemyExpertUnitOfWork(session),
        roster=SQLAlchemyExpertRosterQuery(session),
        identifiers=UUIDIdentifier(),
        clock=SystemClock(),
        publisher=_release_publisher(),
    )
