"""LLM runtime, model-test, audit, identifier, and clock adapters."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail.public import (
    AppendAuditRecordCommand,
    append_audit_record,
)
from app.llm import factory
from app.llm.model_tester import test_card

from ..contracts import (
    ProviderActor,
    ProviderTestResult,
)
from ..domain.models import ProviderRecord

TestCallable = Callable[[str, str, str], Awaitable[dict[str, object]]]


class UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()


class UTCClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class LLMProviderRuntime:
    def synchronize(self, providers: tuple[ProviderRecord, ...]) -> None:
        factory.clear_card_providers()
        inactive_ids: list[str] = []
        tier_ids: dict[str, list[str]] = {}
        primary_by_tier: dict[str, str] = {}
        for provider in sorted(providers, key=lambda item: item.create_time):
            provider_id = f"card_{provider.id.hex}"
            if not provider.is_active:
                inactive_ids.append(provider_id)
                continue
            factory.register_custom_provider(
                provider_id,
                provider.base_url,
                api_key=provider.api_key,
                default_model=provider.model,
            )
            tier_ids.setdefault(provider.tier, [])
            if provider.is_primary:
                tier_ids[provider.tier].insert(0, provider_id)
                primary_by_tier[provider.tier] = provider_id
            else:
                tier_ids[provider.tier].append(provider_id)
        factory.set_provider_status(inactive_ids, primary_by_tier, tier_ids)


class ModelCardTester:
    def __init__(self, callback: TestCallable = test_card) -> None:
        self._callback = callback

    async def test(self, provider: ProviderRecord) -> ProviderTestResult:
        result = await self._callback(
            provider.base_url,
            provider.api_key,
            provider.model,
        )
        raw_latency = result.get("latency_ms")
        return ProviderTestResult(
            status=str(result["status"]),
            latency_ms=raw_latency if isinstance(raw_latency, int) else None,
            message=str(result.get("msg", "")),
        )


class AIProviderAudit:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        actor: ProviderActor | None,
        action: str,
        summary: str,
        provider_id: uuid.UUID | None,
    ) -> None:
        await append_audit_record(
            self._session,
            AppendAuditRecordCommand(
                actor_id=actor.actor_id if actor else None,
                actor_role=actor.role_code if actor else None,
                action=action,
                summary=summary,
                target_type="ai_provider",
                target_id=provider_id,
            ),
        )
