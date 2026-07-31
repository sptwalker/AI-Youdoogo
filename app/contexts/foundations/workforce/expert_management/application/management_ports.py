"""Expert-owned persistence and integration ports."""

from __future__ import annotations

import uuid
from datetime import datetime
from types import TracebackType
from typing import Protocol, Self

from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertReleaseView,
)
from app.contexts.foundations.workforce.expert_management.domain.models import (
    ExpertProfile,
    ExpertRelease,
)


class ExpertRepository(Protocol):
    async def get(self, expert_id: uuid.UUID) -> ExpertProfile | None: ...

    async def get_by_code(self, code: str) -> ExpertProfile | None: ...

    async def get_by_name(self, name: str) -> ExpertProfile | None: ...

    async def add(self, expert: ExpertProfile) -> None: ...

    async def save(self, expert: ExpertProfile) -> None: ...


class ExpertReleaseRepository(Protocol):
    """不可变发布快照仓储（Module 2）：只增快照 + 推进业务表 current 指针。"""

    async def next_version_no(self, expert_id: uuid.UUID) -> int: ...

    async def add(self, release: ExpertRelease) -> None: ...

    async def set_current(self, expert_id: uuid.UUID, release_id: uuid.UUID) -> None: ...

    async def list_releases(self, expert_id: uuid.UUID) -> tuple[ExpertReleaseView, ...]: ...


class ExpertSourceChangePort(Protocol):
    async def publish_expert_changed(self, expert_id: uuid.UUID) -> None: ...


class ExpertUnitOfWork(Protocol):
    @property
    def experts(self) -> ExpertRepository: ...

    @property
    def source_changes(self) -> ExpertSourceChangePort: ...

    @property
    def releases(self) -> ExpertReleaseRepository: ...

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


class ExpertUnitOfWorkFactory(Protocol):
    def __call__(self) -> ExpertUnitOfWork: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...


class Clock(Protocol):
    def now(self) -> datetime: ...
