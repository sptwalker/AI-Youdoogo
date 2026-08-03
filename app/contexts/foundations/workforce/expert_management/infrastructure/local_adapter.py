"""In-process adapter for the published Expert Management object interface."""

from __future__ import annotations

import uuid

from app.contexts.foundations.workforce.expert_management.application.ports import (
    ExpertRosterQueryPort,
    ExpertSnapshotQueryPort,
)
from app.contexts.foundations.workforce.expert_management.application.use_cases import (
    ExpertManagementApplication,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.contracts.management import (
    CreateExpertCommand,
    SeedExpertCommand,
    UpdateExpertCommand,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)


class LocalExpertManagementAdapter:
    """Expose current Expert policy through a session-free method contract."""

    def __init__(
        self,
        *,
        application: ExpertManagementApplication,
        roster: ExpertRosterQueryPort,
        snapshots: ExpertSnapshotQueryPort,
    ) -> None:
        self._application = application
        self._roster = roster
        self._snapshots = snapshots

    async def get_roster(self, expert_id: uuid.UUID) -> ExpertRosterSnapshot | None:
        return await self._roster.get_roster_by_id(expert_id)

    async def get_execution(self, expert_id: uuid.UUID) -> ExpertExecutionSnapshot | None:
        return await self._snapshots.get_by_id(expert_id)

    async def list_roster(
        self, *, include_personal: bool = False
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return await self._application.list_roster(include_personal=include_personal)

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return await self._application.list_department_roster(department_id)

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]:
        return await self._application.count_by_department(include_personal=include_personal)

    async def create(self, command: CreateExpertCommand) -> ExpertRosterSnapshot:
        return await self._application.create(command)

    async def update(self, command: UpdateExpertCommand) -> ExpertRosterSnapshot:
        return await self._application.update(command)

    async def delete(self, expert_id: uuid.UUID) -> None:
        await self._application.delete(expert_id)

    async def seed(self, command: SeedExpertCommand) -> ExpertRosterSnapshot:
        return await self._application.seed(command)
