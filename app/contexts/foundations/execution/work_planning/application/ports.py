"""Work Planning-owned ports."""

from __future__ import annotations

from typing import Protocol

from app.contexts.foundations.execution.work_planning.contracts.planning import (
    WorkIntent,
)


class PlanningModelPort(Protocol):
    async def propose(self, intent: WorkIntent) -> str: ...
