"""Request-scoped Operational Analytics composition."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.application.use_cases import (
    OperationalAnalytics,
)
from app.contexts.business.operational_analytics.infrastructure.connector_adapter import (
    ThinkingDataAnalyticsConnector,
)
from app.contexts.business.operational_analytics.infrastructure.excel_adapter import (
    ExcelWorkbookParser,
)
from app.contexts.business.operational_analytics.infrastructure.sqlalchemy_uow import (
    SQLAlchemyOperationalAnalyticsUnitOfWork,
)


def build_operational_analytics(session: AsyncSession) -> OperationalAnalytics:
    return OperationalAnalytics(
        uow_factory=lambda: SQLAlchemyOperationalAnalyticsUnitOfWork(session),
        parser=ExcelWorkbookParser(),
        connector=ThinkingDataAnalyticsConnector(session),
    )
