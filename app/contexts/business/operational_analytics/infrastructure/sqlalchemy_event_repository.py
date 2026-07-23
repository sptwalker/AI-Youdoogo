"""SQLAlchemy persistence for Operational Analytics event aliases."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.contracts import EventAliasUpdate
from app.models.td_event_alias import TdEventAlias


class SQLAlchemyEventAliasRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def aliases_for(self, view: str) -> dict[str, str]:
        statement = select(TdEventAlias).where(
            TdEventAlias.view == view,
            TdEventAlias.is_delete.is_(False),
        )
        return {
            alias.event_code: alias.display_name
            for alias in (await self._session.execute(statement)).scalars()
        }

    async def save(self, updates: tuple[EventAliasUpdate, ...]) -> int:
        saved = 0
        for update in updates:
            view = update.view.strip()
            code = update.event_code.strip()
            name = update.display_name.strip()
            if not view or not code:
                continue
            statement = select(TdEventAlias).where(
                TdEventAlias.view == view,
                TdEventAlias.event_code == code,
                TdEventAlias.is_delete.is_(False),
            )
            existing = (await self._session.execute(statement)).scalar_one_or_none()
            if not name:
                if existing is not None:
                    existing.is_delete = True
                    saved += 1
                continue
            if existing is None:
                self._session.add(
                    TdEventAlias(view=view, event_code=code, display_name=name)
                )
            else:
                existing.display_name = name
            saved += 1
        await self._session.flush()
        return saved
