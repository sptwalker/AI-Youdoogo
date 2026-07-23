"""Read-only use cases for Agent execution evidence."""

from __future__ import annotations

import uuid

from app.contexts.foundations.execution.agent_execution.application.ports import (
    AgentExecutionRecordQueryPort,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)


class AgentExecutionRecords:
    def __init__(self, records: AgentExecutionRecordQueryPort) -> None:
        self._records = records

    async def get(self, execution_id: uuid.UUID) -> AgentExecutionRecordView | None:
        return await self._records.get(execution_id)

    async def list_recent(self, limit: int) -> tuple[AgentExecutionRecordView, ...]:
        return await self._records.list_recent(limit)
