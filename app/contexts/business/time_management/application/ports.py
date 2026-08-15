"""Time Management 应用层端口：时钟、标识符、三仓储、UoW（结构化 Protocol，便于 Fake 测试）。"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Protocol, Self

from app.contexts.business.time_management.domain.models import (
    FocusSession,
    Schedule,
    TimeLog,
)


class Clock(Protocol):
    def now(self) -> datetime: ...


class IdentifierPort(Protocol):
    def new_id(self) -> uuid.UUID: ...


class ScheduleRepository(Protocol):
    async def add(self, schedule: Schedule) -> None: ...

    async def get(self, schedule_id: uuid.UUID) -> Schedule | None: ...

    async def save(self, schedule: Schedule) -> None: ...

    async def list_for_owner(
        self, *, owner_id: uuid.UUID, status: str | None, limit: int
    ) -> tuple[Schedule, ...]: ...


class FocusSessionRepository(Protocol):
    async def add(self, focus: FocusSession) -> None: ...

    async def get(self, focus_id: uuid.UUID) -> FocusSession | None: ...

    async def save(self, focus: FocusSession) -> None: ...

    async def active_for_owner(self, owner_id: uuid.UUID) -> FocusSession | None: ...


class TimeLogRepository(Protocol):
    async def add(self, log: TimeLog) -> None: ...

    async def list_for_owner_between(
        self, *, owner_id: uuid.UUID, start: date, end: date
    ) -> tuple[TimeLog, ...]: ...


class TimeManagementUnitOfWork(Protocol):
    @property
    def schedules(self) -> ScheduleRepository: ...

    @property
    def focus_sessions(self) -> FocusSessionRepository: ...

    @property
    def time_logs(self) -> TimeLogRepository: ...

    async def __aenter__(self) -> Self: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


TimeManagementUnitOfWorkFactory = Callable[[], TimeManagementUnitOfWork]
