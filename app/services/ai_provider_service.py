"""One-way compatibility facade for AI Provider Management."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.system_configuration import (
    ai_provider_management,
)
from app.llm.model_tester import test_card as test_card


async def get_provider(
    db: AsyncSession,
    provider_id: uuid.UUID,
) -> ai_provider_management.ProviderSnapshot:
    return await ai_provider_management.operations.get_provider(db, provider_id)


async def create(
    db: AsyncSession,
    *,
    name: str,
    tier: str,
    base_url: str,
    api_key: str,
    model: str,
) -> ai_provider_management.ProviderSnapshot:
    return await ai_provider_management.operations.create_provider_record(
        db,
        ai_provider_management.CreateProviderCommand(
            name=name,
            tier=tier,
            base_url=base_url,
            api_key=api_key,
            model=model,
        ),
    )


async def update(
    db: AsyncSession,
    provider_id: uuid.UUID,
    *,
    name: str | None = None,
    tier: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
) -> ai_provider_management.ProviderSnapshot:
    return await ai_provider_management.operations.update_provider_record(
        db,
        ai_provider_management.UpdateProviderCommand(
            provider_id=provider_id,
            name=name,
            tier=tier,
            base_url=base_url,
            api_key=api_key,
            model=model,
        ),
    )


async def delete(db: AsyncSession, provider_id: uuid.UUID) -> None:
    await ai_provider_management.operations.delete_provider_record(db, provider_id)


async def set_primary(
    db: AsyncSession,
    provider_id: uuid.UUID,
) -> ai_provider_management.ProviderSnapshot:
    return await ai_provider_management.operations.set_primary_record(db, provider_id)


async def toggle_active(
    db: AsyncSession,
    provider_id: uuid.UUID,
    active: bool,
) -> ai_provider_management.ProviderSnapshot:
    return await ai_provider_management.operations.toggle_active_record(
        db, provider_id, active
    )


async def test_provider(db: AsyncSession, provider_id: uuid.UUID) -> dict[str, object]:
    result = await ai_provider_management.operations.test_provider_record(
        db,
        provider_id,
        tester=ai_provider_management.ModelCardTester(test_card),
    )
    return result.to_dict()


async def test_all(db: AsyncSession) -> list[dict[str, object]]:
    results = await ai_provider_management.operations.test_all_provider_records(
        db,
        tester=ai_provider_management.ModelCardTester(test_card),
    )
    return [result.to_dict() for result in results]


async def list_providers(db: AsyncSession) -> list[dict[str, object]]:
    providers = await ai_provider_management.operations.list_providers(db)
    return [provider.to_dict() for provider in providers]


async def seed_from_env(db: AsyncSession) -> int:
    return await ai_provider_management.operations.seed_providers_from_environment(db)


async def sync_to_factory(db: AsyncSession) -> None:
    await ai_provider_management.operations.synchronize_provider_runtime(db)
