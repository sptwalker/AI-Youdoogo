"""ThinkingData adapter for Operational Analytics."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.application.contracts import (
    AnalyticsConnectorConfiguration,
)
from app.contexts.business.operational_analytics.application.mapping import (
    resolve_event_views,
    resolve_mapping,
)
from app.contexts.business.operational_analytics.contracts import AnalyticsConnectorFailure
from app.core import runtime_config
from app.core.config import get_settings
from app.integrations.thinkingdata import client as thinkingdata
from app.models.sys_config import SysConfig


class ThinkingDataAnalyticsConnector:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._configuration: AnalyticsConnectorConfiguration | None = None

    async def configuration(self) -> AnalyticsConnectorConfiguration:
        statement = select(SysConfig).where(
            SysConfig.key.in_(
                (
                    "td_base_url",
                    "td_api_secret",
                    "td_daily_metrics_sql",
                    "td_field_mapping",
                    "td_event_views",
                )
            ),
            SysConfig.is_delete.is_(False),
        )
        values = {
            row.key: row.value for row in (await self._session.execute(statement)).scalars()
        }
        settings = get_settings()
        self._configuration = AnalyticsConnectorConfiguration(
            base_url=str(values.get("td_base_url") or settings.td_base_url or ""),
            api_secret=str(
                runtime_config.effective("td_api_secret", settings.td_api_secret) or ""
            ),
            sql_template=str(values.get("td_daily_metrics_sql") or ""),
            mapping=resolve_mapping(values.get("td_field_mapping")),
            event_views=resolve_event_views(values.get("td_event_views")),
        )
        return self._configuration

    async def query(self, sql: str) -> list[dict[str, object]]:
        configuration = self._configuration or await self.configuration()
        connector = thinkingdata.ThinkingDataClient(
            base_url=configuration.base_url,
            api_secret=configuration.api_secret,
        )
        try:
            return await connector.query_sql(sql)
        except thinkingdata.ThinkingDataError as exc:
            raise AnalyticsConnectorFailure(str(exc)) from exc
        finally:
            await connector.close()
