"""SQLAlchemy read adapter for Agent execution evidence."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)
from app.models.agent import AgentTaskRecord


def _view(record: AgentTaskRecord) -> AgentExecutionRecordView:
    return AgentExecutionRecordView(
        id=record.id,
        agent_role_id=record.agent_role_id,
        task_type=record.task_type,
        input_summary=record.input_summary,
        output_content=record.output_content,
        model_used=record.model_used,
        status=record.status,
        error_msg=record.error_msg,
        duration_ms=record.duration_ms,
        create_time=record.create_time,
    )


class SQLAlchemyAgentExecutionRecordQuery:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get(self, execution_id: uuid.UUID) -> AgentExecutionRecordView | None:
        record = await self._session.get(AgentTaskRecord, execution_id)
        if record is None or record.is_delete:
            return None
        return _view(record)

    async def list_recent(self, limit: int) -> tuple[AgentExecutionRecordView, ...]:
        statement = (
            select(AgentTaskRecord)
            .where(AgentTaskRecord.is_delete.is_(False))
            .order_by(AgentTaskRecord.create_time.desc())
            .limit(limit)
        )
        return tuple(_view(record) for record in (await self._session.execute(statement)).scalars())
