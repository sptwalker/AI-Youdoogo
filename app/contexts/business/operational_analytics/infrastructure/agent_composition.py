"""Request-scoped composition for operational Agent analysis."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.application.agent_use_cases import (
    OperationalAgentAnalytics,
)
from app.contexts.business.operational_analytics.infrastructure.agent_adapters import (
    FeishuOperationalNotification,
    NullOperationalNotification,
    PublishedOperationalAgentAdapter,
    PublishedOperationalExpertAdapter,
    SQLAlchemyOperationalMetricHistory,
)


def build_operational_agent_analytics(
    session: AsyncSession,
    *,
    notifications_enabled: bool,
) -> OperationalAgentAnalytics:
    notifications = (
        FeishuOperationalNotification()
        if notifications_enabled
        else NullOperationalNotification()
    )
    return OperationalAgentAnalytics(
        metrics=SQLAlchemyOperationalMetricHistory(session),
        experts=PublishedOperationalExpertAdapter(session),
        agents=PublishedOperationalAgentAdapter(session),
        notifications=notifications,
    )
