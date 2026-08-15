"""会前提醒钩子（docs/27-B B3.2）——为即将开始的会议/日程产出「会前提醒」，红线不旁路。

两条路径，复用既有能力零重复红线代码：
- **自我提醒**（发给本人）：建一张本人草稿 Task 进收件箱（`creator_id=owner` → 落 `my_tasks`
  投影，status=created 真人可编辑/驳回），内部不停点。
- **对外提醒**（通知他人）：**不在此直发**；复用点对点触达红线（`feishu_notify_person`
  compose→publish），`requires_human_review` 恒 True → 编排步执行前必停 `waiting_human`。

到点判定 `is_due` 是纯函数（可单测）。
ponytail: 只做「判定 + 自我提醒建卡 / 对外必停」的最小钩子；定时轮询扫描（scan_once + session
    工厂，仿 report_scheduler）与对外提醒自动起编排留待接线时再加，非本阶段红线所需。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.task_management import public as task_management
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    requires_human_review,
)

# 对外会前提醒复用的点对点触达能力键（其红线：非 AUTOMATIC → 必停 waiting_human）。
_OUTBOUND_CAPABILITY = "feishu_notify_person"


def is_due(meeting_start: datetime, now: datetime, *, lead_minutes: int = 15) -> bool:
    """会前提醒到点判定：now 落在 [start - lead, start) 区间即到点（会已开始不再提醒）。"""
    if lead_minutes <= 0:
        return False
    return meeting_start - timedelta(minutes=lead_minutes) <= now < meeting_start


def reminder_requires_human_review(*, is_outbound: bool) -> bool:
    """会前提醒红线判定：对外提醒复用点对点触达红线（必停）；自我提醒内部不停。"""
    return is_outbound and requires_human_review(_OUTBOUND_CAPABILITY)


async def push_reminder(
    session: AsyncSession,
    *,
    owner_id: uuid.UUID,
    meeting_title: str,
    is_outbound: bool,
) -> dict[str, Any]:
    """产出会前提醒。

    自我提醒 → 建本人草稿 Task 进收件箱，``stopped=False``。
    对外提醒 → 不直发，``stopped=True``（须真人经 compose→publish 验收后才对外），不建卡。
    """
    if reminder_requires_human_review(is_outbound=is_outbound):
        return {"stopped": True, "capability": _OUTBOUND_CAPABILITY, "task": None}
    task = await task_management.create_task(
        session,
        task_management.CreateTaskRequest(
            title=f"[会前提醒] {meeting_title}",
            task_type="self_reminder",
            creator_id=owner_id,
        ),
    )
    return {"stopped": False, "capability": None, "task": task}
