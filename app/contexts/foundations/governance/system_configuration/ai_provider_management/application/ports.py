"""AI Provider-owned persistence and integration ports."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from ..contracts import ProviderTestResult
from ..domain.models import ProviderRecord


class ProviderRepositoryPort(Protocol):
    async def get(self, provider_id: uuid.UUID) -> ProviderRecord | None: ...

    async def add(self, provider: ProviderRecord) -> None: ...

    async def save(self, provider: ProviderRecord) -> None: ...

    async def list_all(self) -> list[ProviderRecord]: ...

    async def list_active_by_tier(self, tier: str) -> list[ProviderRecord]: ...


class ProviderUnitOfWork(Protocol):
    @property
    def providers(self) -> ProviderRepositoryPort: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None: ...

    async def flush(self) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


ProviderUnitOfWorkFactory = Callable[[], ProviderUnitOfWork]


class ProviderRuntimePort(Protocol):
    def synchronize(self, providers: tuple[ProviderRecord, ...]) -> None: ...


class ProviderTesterPort(Protocol):
    async def test(self, provider: ProviderRecord) -> ProviderTestResult: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...


class ClockPort(Protocol):
    def now(self) -> datetime: ...
