"""Request-scoped composition for AI Provider Management."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from ..application.ports import ProviderTesterPort
from ..application.use_cases import AIProviderManagement
from .adapters import (
    LLMProviderRuntime,
    ModelCardTester,
    UTCClock,
    UUIDIdentifier,
)
from .sqlalchemy_uow import SQLAlchemyProviderUnitOfWork


def build_ai_provider_management(
    session: AsyncSession,
    *,
    tester: ProviderTesterPort | None = None,
) -> AIProviderManagement:
    return AIProviderManagement(
        units=lambda: SQLAlchemyProviderUnitOfWork(session),
        runtime=LLMProviderRuntime(),
        tester=tester or ModelCardTester(),
        identifiers=UUIDIdentifier(),
        clock=UTCClock(),
    )
