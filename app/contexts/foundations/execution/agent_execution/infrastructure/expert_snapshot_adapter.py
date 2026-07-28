"""Adapter from Agent Execution's expert port to Expert Management's public query."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_directory_port,
)


class PublishedExpertSnapshotAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._directory = build_local_expert_directory_port(session)

    async def get_by_id(self, expert_id: uuid.UUID) -> ExpertExecutionSnapshot | None:
        return await self._directory.get_execution(expert_id)
