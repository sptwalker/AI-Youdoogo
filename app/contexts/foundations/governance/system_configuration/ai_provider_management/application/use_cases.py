"""AI Provider CRUD, failover, runtime synchronization, and tests."""

from __future__ import annotations

import uuid

from app.contexts.shared_kernel import ResourceNotFound

from ..contracts import (
    CreateProviderCommand,
    ProviderSnapshot,
    ProviderTestResult,
    ProviderTestSummary,
    UpdateProviderCommand,
)
from ..domain.models import (
    TIER_DAILY,
    TIER_REASONING,
    ProviderRecord,
    secret_hint,
    validate_tier,
)
from .ports import (
    ClockPort,
    IdentifierPort,
    ProviderRepositoryPort,
    ProviderRuntimePort,
    ProviderTesterPort,
    ProviderUnitOfWorkFactory,
)


def _snapshot(provider: ProviderRecord) -> ProviderSnapshot:
    return ProviderSnapshot(
        provider_id=provider.id,
        name=provider.name,
        tier=provider.tier,
        base_url=provider.base_url,
        model=provider.model,
        api_key_hint=provider.api_key_hint,
        api_key_set=bool(provider.api_key),
        is_primary=provider.is_primary,
        is_active=provider.is_active,
        last_test_status=provider.last_test_status,
        last_test_at=provider.last_test_at,
        last_test_latency_ms=provider.last_test_latency_ms,
        last_test_message=provider.last_test_message,
    )


class AIProviderManagement:
    def __init__(
        self,
        *,
        units: ProviderUnitOfWorkFactory,
        runtime: ProviderRuntimePort,
        tester: ProviderTesterPort,
        identifiers: IdentifierPort,
        clock: ClockPort,
    ) -> None:
        self._units = units
        self._runtime = runtime
        self._tester = tester
        self._identifiers = identifiers
        self._clock = clock

    async def get(self, provider_id: uuid.UUID) -> ProviderSnapshot:
        async with self._units() as unit:
            provider = await self._required(unit.providers, provider_id)
        return _snapshot(provider)

    async def list(self) -> tuple[ProviderSnapshot, ...]:
        async with self._units() as unit:
            providers = await unit.providers.list_all()
        return tuple(_snapshot(provider) for provider in providers)

    async def create(self, command: CreateProviderCommand) -> ProviderSnapshot:
        validate_tier(command.tier)
        async with self._units() as unit:
            active = await unit.providers.list_active_by_tier(command.tier)
            provider = ProviderRecord(
                id=self._identifiers.new_id(),
                name=command.name,
                tier=command.tier,
                base_url=command.base_url.strip(),
                api_key=command.api_key.strip(),
                api_key_hint=secret_hint(command.api_key),
                model=command.model.strip(),
                is_primary=not active,
                is_active=True,
                create_time=self._clock.now(),
            )
            await unit.providers.add(provider)
            await unit.commit()
        return _snapshot(provider)

    async def update(self, command: UpdateProviderCommand) -> ProviderSnapshot:
        async with self._units() as unit:
            provider = await self._required(unit.providers, command.provider_id)
            provider.update(
                name=command.name,
                tier=command.tier,
                base_url=command.base_url,
                api_key=command.api_key,
                model=command.model,
            )
            await unit.providers.save(provider)
            await unit.commit()
        return _snapshot(provider)

    async def delete(self, provider_id: uuid.UUID) -> None:
        async with self._units() as unit:
            provider = await self._required(unit.providers, provider_id)
            tier = provider.tier
            provider.mark_deleted()
            await unit.providers.save(provider)
            await unit.flush()
            await self._promote_if_needed(unit.providers, tier)
            await unit.commit()

    async def set_primary(self, provider_id: uuid.UUID) -> ProviderSnapshot:
        async with self._units() as unit:
            provider = await self._required(unit.providers, provider_id)
            provider.make_primary()
            for candidate in await unit.providers.list_active_by_tier(provider.tier):
                candidate.is_primary = candidate.id == provider.id
                await unit.providers.save(candidate)
            await unit.commit()
        return _snapshot(provider)

    async def toggle_active(
        self, provider_id: uuid.UUID, active: bool
    ) -> ProviderSnapshot:
        async with self._units() as unit:
            provider = await self._required(unit.providers, provider_id)
            tier = provider.tier
            provider.set_active(active)
            await unit.providers.save(provider)
            await unit.flush()
            await self._promote_if_needed(unit.providers, tier)
            await unit.commit()
        return _snapshot(provider)

    async def test_provider(self, provider_id: uuid.UUID) -> ProviderTestResult:
        async with self._units() as unit:
            provider = await self._required(unit.providers, provider_id)
            result = await self._tester.test(provider)
            provider.record_test(
                status=result.status,
                latency_ms=result.latency_ms,
                message=result.message,
                tested_at=self._clock.now(),
            )
            await unit.providers.save(provider)
            await unit.commit()
        return result

    async def test_all(self) -> tuple[ProviderTestSummary, ...]:
        async with self._units() as unit:
            providers = await unit.providers.list_all()
            summaries: list[ProviderTestSummary] = []
            for provider in providers:
                if not provider.is_active:
                    result = ProviderTestResult("disabled", None, "已禁用")
                else:
                    result = await self._tester.test(provider)
                    provider.record_test(
                        status=result.status,
                        latency_ms=result.latency_ms,
                        message=result.message,
                        tested_at=self._clock.now(),
                    )
                    await unit.providers.save(provider)
                summaries.append(ProviderTestSummary(provider.id, result))
            await unit.commit()
        return tuple(summaries)

    async def synchronize_runtime(self) -> None:
        async with self._units() as unit:
            providers = await unit.providers.list_all()
        self._runtime.synchronize(tuple(providers))

    async def seed_from_api_key(self, api_key: str) -> int:
        async with self._units() as unit:
            if await unit.providers.list_all():
                return 0
        key = api_key.strip()
        if not key:
            return 0
        await self.create(
            CreateProviderCommand(
                name="DeepSeek 日常",
                tier=TIER_DAILY,
                base_url="https://api.deepseek.com",
                api_key=key,
                model="deepseek-chat",
            )
        )
        await self.create(
            CreateProviderCommand(
                name="DeepSeek 推理",
                tier=TIER_REASONING,
                base_url="https://api.deepseek.com",
                api_key=key,
                model="deepseek-reasoner",
            )
        )
        return 2

    @staticmethod
    async def _promote_if_needed(
        repository: ProviderRepositoryPort,
        tier: str,
    ) -> None:
        providers = await repository.list_active_by_tier(tier)
        if not providers or any(provider.is_primary for provider in providers):
            return
        providers[0].is_primary = True
        await repository.save(providers[0])

    @staticmethod
    async def _required(
        repository: ProviderRepositoryPort,
        provider_id: uuid.UUID,
    ) -> ProviderRecord:
        provider = await repository.get(provider_id)
        if provider is None or provider.is_deleted:
            raise ResourceNotFound("AI 卡片不存在")
        return provider
