"""Catalog snapshot adapter over existing connector, config, and alias stores."""

from __future__ import annotations

import json
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management import public as connectors
from app.contexts.foundations.integration.governed_data_query.contracts import (
    CatalogSource,
    CatalogView,
    DataCatalogSnapshot,
    NamedEvent,
)
from app.models.sys_config import SysConfig
from app.models.td_event_alias import TdEventAlias

logger = logging.getLogger(__name__)

DEFAULT_VIEWS = (
    {"view": "v_event_4", "product": "盒子"},
    {"view": "v_event_5", "product": "游戏"},
    {"view": "v_event_6", "product": "APP"},
)


def resolve_views(raw: Any) -> tuple[dict[str, str], ...]:
    if isinstance(raw, str) and raw.strip():
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("td_event_views 非法 JSON，回退默认视图")
            return DEFAULT_VIEWS
    if isinstance(raw, list):
        parsed = tuple(
            {"view": str(item["view"]), "product": str(item.get("product") or item["view"])}
            for item in raw
            if isinstance(item, dict) and item.get("view")
        )
        return parsed or DEFAULT_VIEWS
    return DEFAULT_VIEWS


class SQLAlchemyDataCatalogAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot(self) -> DataCatalogSnapshot:
        connector_snapshots = await connectors.connector_catalog(self._session)
        sources = tuple(
            CatalogSource(
                name=connector.name,
                code=connector.code,
                is_active=connector.is_active,
            )
            for connector in connector_snapshots
            if connector.connector_type == "thinkingdata"
        )
        config_statement = select(SysConfig.value).where(
            SysConfig.key == "td_event_views",
            SysConfig.is_delete.is_(False),
        )
        raw_views = (await self._session.execute(config_statement)).scalar_one_or_none()
        aliases = tuple(
            (
                await self._session.execute(
                    select(TdEventAlias).where(TdEventAlias.is_delete.is_(False))
                )
            ).scalars()
        )
        by_view: dict[str, list[NamedEvent]] = {}
        for alias in aliases:
            by_view.setdefault(alias.view, []).append(
                NamedEvent(
                    event_code=alias.event_code,
                    display_name=alias.display_name,
                )
            )
        views = tuple(
            CatalogView(
                view=item["view"],
                product=item["product"],
                named_events=tuple(by_view.get(item["view"], ())),
            )
            for item in resolve_views(raw_views)
        )
        return DataCatalogSnapshot(sources=sources, views=views)
