"""Request-scoped published AI Provider operations."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import config

from ..application.ports import ProviderTesterPort
from ..contracts import (
    CreateProviderCommand,
    ProviderActor,
    ProviderSnapshot,
    ProviderTestResult,
    ProviderTestSummary,
    UpdateProviderCommand,
)
from ..infrastructure.adapters import AIProviderAudit
from ..infrastructure.composition import build_ai_provider_management


async def list_providers(session: AsyncSession) -> tuple[ProviderSnapshot, ...]:
    return await build_ai_provider_management(session).list()


async def get_provider(
    session: AsyncSession,
    provider_id: uuid.UUID,
) -> ProviderSnapshot:
    return await build_ai_provider_management(session).get(provider_id)


async def create_provider_record(
    session: AsyncSession,
    command: CreateProviderCommand,
) -> ProviderSnapshot:
    return await build_ai_provider_management(session).create(command)


async def update_provider_record(
    session: AsyncSession,
    command: UpdateProviderCommand,
) -> ProviderSnapshot:
    return await build_ai_provider_management(session).update(command)


async def delete_provider_record(
    session: AsyncSession,
    provider_id: uuid.UUID,
) -> None:
    await build_ai_provider_management(session).delete(provider_id)


async def set_primary_record(
    session: AsyncSession,
    provider_id: uuid.UUID,
) -> ProviderSnapshot:
    return await build_ai_provider_management(session).set_primary(provider_id)


async def toggle_active_record(
    session: AsyncSession,
    provider_id: uuid.UUID,
    active: bool,
) -> ProviderSnapshot:
    return await build_ai_provider_management(session).toggle_active(provider_id, active)


async def test_provider_record(
    session: AsyncSession,
    provider_id: uuid.UUID,
    *,
    tester: ProviderTesterPort | None = None,
) -> ProviderTestResult:
    return await build_ai_provider_management(session, tester=tester).test_provider(
        provider_id
    )


async def test_all_provider_records(
    session: AsyncSession,
    *,
    tester: ProviderTesterPort | None = None,
) -> tuple[ProviderTestSummary, ...]:
    return await build_ai_provider_management(session, tester=tester).test_all()


async def synchronize_provider_runtime(session: AsyncSession) -> None:
    await build_ai_provider_management(session).synchronize_runtime()


async def seed_providers_from_environment(session: AsyncSession) -> int:
    return await build_ai_provider_management(session).seed_from_api_key(
        config.get_settings().deepseek_api_key
    )


async def create_provider(
    session: AsyncSession,
    command: CreateProviderCommand,
) -> ProviderSnapshot:
    provider = await create_provider_record(session, command)
    await synchronize_provider_runtime(session)
    await AIProviderAudit(session).record(
        actor=command.actor,
        action="ai_provider.create",
        summary=f"新增 AI 卡片 {provider.name}",
        provider_id=provider.provider_id,
    )
    return provider


async def update_provider(
    session: AsyncSession,
    command: UpdateProviderCommand,
) -> ProviderSnapshot:
    provider = await update_provider_record(session, command)
    await synchronize_provider_runtime(session)
    await AIProviderAudit(session).record(
        actor=command.actor,
        action="ai_provider.update",
        summary=f"修改 AI 卡片 {provider.name}",
        provider_id=provider.provider_id,
    )
    return provider


async def delete_provider(
    session: AsyncSession,
    provider_id: uuid.UUID,
    *,
    actor: ProviderActor | None,
) -> None:
    await delete_provider_record(session, provider_id)
    await synchronize_provider_runtime(session)
    await AIProviderAudit(session).record(
        actor=actor,
        action="ai_provider.delete",
        summary="删除 AI 卡片",
        provider_id=provider_id,
    )


async def set_primary_provider(
    session: AsyncSession,
    provider_id: uuid.UUID,
    *,
    actor: ProviderActor | None,
) -> ProviderSnapshot:
    provider = await set_primary_record(session, provider_id)
    await synchronize_provider_runtime(session)
    await AIProviderAudit(session).record(
        actor=actor,
        action="ai_provider.primary",
        summary=f"设主用 AI 卡片 {provider.name}",
        provider_id=provider.provider_id,
    )
    return provider


async def toggle_provider(
    session: AsyncSession,
    provider_id: uuid.UUID,
    active: bool,
    *,
    actor: ProviderActor | None,
) -> ProviderSnapshot:
    provider = await toggle_active_record(session, provider_id, active)
    await synchronize_provider_runtime(session)
    verb = "启用" if active else "禁用"
    await AIProviderAudit(session).record(
        actor=actor,
        action="ai_provider.toggle",
        summary=f"{verb} AI 卡片 {provider.name}",
        provider_id=provider.provider_id,
    )
    return provider
