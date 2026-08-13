"""report_schedule 表的**唯一**持久化写者（架构门禁：一模型一写者 Context）。

只两条职责：列出启用中的调度快照、把某条标记为「本期已发起」。到点判定/发起编排都在 bootstrap，
这里不含业务时序逻辑。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.report_scheduling.contracts import ScheduleView
from app.models.report_schedule import ReportSchedule


async def list_enabled(session: AsyncSession) -> list[ScheduleView]:
    """返回启用中的调度快照（脱离 Session，避免 commit 后懒加载）。"""
    rows = (
        await session.execute(
            select(ReportSchedule).where(
                ReportSchedule.enabled.is_(True),
                ReportSchedule.is_delete.is_(False),
            )
        )
    ).scalars()
    return [
        ScheduleView(
            id=row.id,
            name=row.name,
            title=row.title,
            request_text=row.request_text,
            creator_id=row.creator_id,
            assignee_agent_id=row.assignee_agent_id,
            day_of_month=row.day_of_month,
            hour=row.hour,
            enabled=row.enabled,
            last_fired_period=row.last_fired_period,
        )
        for row in rows
    ]


async def mark_fired(session: AsyncSession, schedule_id: uuid.UUID, period: str) -> None:
    """把某条调度标记为该 period（YYYY-MM）已发起——幂等游标，防同月重发。"""
    await session.execute(
        update(ReportSchedule)
        .where(ReportSchedule.id == schedule_id)
        .values(last_fired_period=period)
    )
