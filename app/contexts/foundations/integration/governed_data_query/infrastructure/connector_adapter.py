"""ThinkingData connector execution adapter."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.governed_data_query.application.contracts import (
    ConnectorQueryConfiguration,
)
from app.contexts.foundations.integration.governed_data_query.application.ports import (
    ConnectorExecutionFailure,
)
from app.core import runtime_config
from app.core.config import get_settings
from app.integrations.thinkingdata import client as thinkingdata
from app.models.sys_config import SysConfig


class ThinkingDataConnectorAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def configuration(self) -> ConnectorQueryConfiguration:
        statement = select(SysConfig).where(
            SysConfig.key.in_(("td_base_url", "td_api_secret")),
            SysConfig.is_delete.is_(False),
        )
        values = {
            row.key: row.value for row in (await self._session.execute(statement)).scalars()
        }
        settings = get_settings()
        return ConnectorQueryConfiguration(
            base_url=str(values.get("td_base_url") or settings.td_base_url or ""),
            api_secret=str(
                runtime_config.effective("td_api_secret", settings.td_api_secret) or ""
            ),
        )

    async def execute(
        self,
        configuration: ConnectorQueryConfiguration,
        sql: str,
        *,
        timeout: int,
    ) -> list[dict[str, object]]:
        connector = thinkingdata.ThinkingDataClient(
            base_url=configuration.base_url,
            api_secret=configuration.api_secret,
        )
        try:
            return await connector.query_sql(sql, timeout_seconds=timeout)
        except thinkingdata.ThinkingDataError as exc:
            raise ConnectorExecutionFailure(str(exc)) from exc
        finally:
            await connector.close()
