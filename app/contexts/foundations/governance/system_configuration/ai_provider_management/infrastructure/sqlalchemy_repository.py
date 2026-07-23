"""SQLAlchemy persistence for AI Provider Management."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider import AiProvider

from ..domain.models import ProviderRecord


def _to_domain(row: AiProvider) -> ProviderRecord:
    return ProviderRecord(
        id=row.id,
        name=row.name,
        tier=row.tier,
        base_url=row.base_url,
        api_key=row.api_key,
        api_key_hint=row.api_key_hint,
        model=row.model,
        is_primary=row.is_primary,
        is_active=row.is_active,
        create_time=row.create_time,
        last_test_status=row.last_test_status,
        last_test_at=row.last_test_at,
        last_test_latency_ms=row.last_test_latency_ms,
        last_test_message=row.last_test_msg,
        is_deleted=row.is_delete,
    )


def _to_row(provider: ProviderRecord) -> AiProvider:
    return AiProvider(
        id=provider.id,
        name=provider.name,
        tier=provider.tier,
        base_url=provider.base_url,
        api_key=provider.api_key,
        api_key_hint=provider.api_key_hint,
        model=provider.model,
        is_primary=provider.is_primary,
        is_active=provider.is_active,
        create_time=provider.create_time,
        last_test_status=provider.last_test_status,
        last_test_at=provider.last_test_at,
        last_test_latency_ms=provider.last_test_latency_ms,
        last_test_msg=provider.last_test_message,
        is_delete=provider.is_deleted,
    )


class SQLAlchemyProviderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rows: dict[uuid.UUID, AiProvider] = {}

    async def get(self, provider_id: uuid.UUID) -> ProviderRecord | None:
        row = await self._session.get(AiProvider, provider_id)
        if row is None:
            return None
        self._rows[row.id] = row
        return _to_domain(row)

    async def add(self, provider: ProviderRecord) -> None:
        row = _to_row(provider)
        self._rows[provider.id] = row
        self._session.add(row)

    async def save(self, provider: ProviderRecord) -> None:
        row = self._rows.get(provider.id)
        if row is None:
            row = await self._session.get(AiProvider, provider.id)
        if row is None:
            return
        self._rows[provider.id] = row
        row.name = provider.name
        row.tier = provider.tier
        row.base_url = provider.base_url
        row.api_key = provider.api_key
        row.api_key_hint = provider.api_key_hint
        row.model = provider.model
        row.is_primary = provider.is_primary
        row.is_active = provider.is_active
        row.last_test_status = provider.last_test_status
        row.last_test_at = provider.last_test_at
        row.last_test_latency_ms = provider.last_test_latency_ms
        row.last_test_msg = provider.last_test_message
        row.is_delete = provider.is_deleted

    async def list_all(self) -> list[ProviderRecord]:
        statement = (
            select(AiProvider)
            .where(AiProvider.is_delete.is_(False))
            .order_by(AiProvider.tier, AiProvider.create_time)
        )
        rows = list((await self._session.execute(statement)).scalars())
        self._rows.update({row.id: row for row in rows})
        return [_to_domain(row) for row in rows]

    async def list_active_by_tier(self, tier: str) -> list[ProviderRecord]:
        statement = (
            select(AiProvider)
            .where(
                AiProvider.tier == tier,
                AiProvider.is_active.is_(True),
                AiProvider.is_delete.is_(False),
            )
            .order_by(AiProvider.create_time)
        )
        rows = list((await self._session.execute(statement)).scalars())
        self._rows.update({row.id: row for row in rows})
        return [_to_domain(row) for row in rows]
