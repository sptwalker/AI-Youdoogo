"""Adapters for operational AI analysis, expert lookup, and notification."""

from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.operational_analytics.agent_contracts import (
    MetricRowInput,
)
from app.contexts.business.operational_analytics.infrastructure.sqlalchemy_repository import (
    SQLAlchemyDailyMetricRepository,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)
from app.contexts.foundations.execution.agent_execution.public import (
    execute_agent,
    get_execution_record,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.public import (
    build_local_expert_directory_port,
)
from app.integrations.feishu import notify


class SQLAlchemyOperationalMetricHistory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._records = SQLAlchemyDailyMetricRepository(session)

    async def list_for_date(self, stat_date: date) -> tuple[MetricRowInput, ...]:
        snapshots = await self._records.list_for_date(stat_date)
        result = tuple(
            MetricRowInput(
                stat_date=snapshot.stat_date.isoformat(),
                product=snapshot.product,
                dau=snapshot.dau,
                new_users=snapshot.new_users,
                retention_d1=snapshot.retention_d1,
            )
            for snapshot in snapshots
        )
        if self._session.in_transaction():
            await self._session.rollback()
        return result


class PublishedOperationalExpertAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._directory = build_local_expert_directory_port(session)

    async def get_by_code(self, code: str) -> ExpertExecutionSnapshot | None:
        roster = await self._directory.list_roster(include_personal=True)
        match = next(
            (expert for expert in roster if expert.code == code and expert.is_active),
            None,
        )
        snapshot = (
            await self._directory.get_execution(match.expert_id)
            if match is not None
            else None
        )
        if self._session.in_transaction():
            await self._session.rollback()
        return snapshot


class PublishedOperationalAgentAdapter:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionRecordView:
        result = await execute_agent(self._session, request)
        if result.execution_id is None:
            raise RuntimeError("Agent execution result was not recorded")
        record = await get_execution_record(self._session, result.execution_id)
        if record is None:
            raise RuntimeError("Agent execution record is unavailable")
        return record


class FeishuOperationalNotification:
    async def push(self, message: str) -> None:
        await notify.push_ops_message(message)


class NullOperationalNotification:
    async def push(self, message: str) -> None:
        del message
