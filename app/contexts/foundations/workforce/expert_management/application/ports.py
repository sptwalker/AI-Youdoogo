"""Expert Management query ports."""

from __future__ import annotations

import uuid
from typing import Protocol

from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)


class ExpertSnapshotQueryPort(Protocol):
    """Read active experts as immutable execution snapshots."""

    async def get_by_id(self, expert_id: uuid.UUID) -> ExpertExecutionSnapshot | None: ...

    async def get_by_name(self, name: str) -> ExpertExecutionSnapshot | None: ...

    async def get_by_code(self, code: str) -> ExpertExecutionSnapshot | None: ...


class ExpertRosterQueryPort(Protocol):
    """Publish roster views while keeping personal assistants opt-in."""

    async def get_roster_by_id(self, expert_id: uuid.UUID) -> ExpertRosterSnapshot | None: ...

    async def list_roster(
        self, *, include_personal: bool = False
    ) -> tuple[ExpertRosterSnapshot, ...]: ...

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]: ...

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]: ...
