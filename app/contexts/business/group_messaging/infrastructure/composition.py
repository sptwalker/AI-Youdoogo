"""Request-scoped composition for Group Messaging during route migration."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.group_messaging.application.use_cases import (
    GroupMessagingApplication,
)
from app.contexts.business.group_messaging.infrastructure.adapters import (
    KnowledgeAttachmentStorageAdapter,
    LegacyAgentReplyAdapter,
    LegacyPromotionAdapter,
    OrganizationalMemoryArchiveAdapter,
    RedisRealtimeDeliveryAdapter,
    RedisRealtimeSubscriptionAdapter,
    SQLAlchemyOutboxAdapter,
    SystemClock,
    UUIDIdentifier,
)
from app.contexts.business.group_messaging.infrastructure.sqlalchemy_uow import (
    SQLAlchemyGroupMessagingUnitOfWork,
)


def build_group_messaging_application(
    session: AsyncSession,
) -> GroupMessagingApplication:
    return GroupMessagingApplication(
        uow_factory=lambda: SQLAlchemyGroupMessagingUnitOfWork(session),
        realtime_delivery=RedisRealtimeDeliveryAdapter(),
        realtime_subscription=RedisRealtimeSubscriptionAdapter(),
        agent_replies=LegacyAgentReplyAdapter(session),
        attachment_storage=KnowledgeAttachmentStorageAdapter(),
        archive_port=OrganizationalMemoryArchiveAdapter(session),
        promotion_port=LegacyPromotionAdapter(session),
        outbox_port=SQLAlchemyOutboxAdapter(session),
        clock=SystemClock(),
        identifiers=UUIDIdentifier(),
    )
