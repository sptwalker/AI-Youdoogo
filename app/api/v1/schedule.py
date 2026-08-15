"""个人日程只读/确认接口（docs/27-B B4）：时间线/日历视图拉数 + 确认建议。

行级隔离：全部按当前登录人 `owner_id`；确认命中他人 → `ResourceNotFound`(404)。
红线：智能排程只出建议（suggested），此处 `confirm` 才生效（对齐 B2.2）。
ponytail: 先只读 + 确认两端点满足视图；建议生成/手工建日程沿用既有用例，需要时再挂路由。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.contexts.business.time_management.application.contracts import ScheduleResult
from app.contexts.business.time_management.entrypoints import operations as time_management
from app.platform.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(prefix="/schedules", tags=["schedules"])

DB = Annotated[AsyncSession, Depends(get_db)]


def _serialize(schedule: ScheduleResult) -> dict[str, Any]:
    return {
        "id": str(schedule.id),
        "title": schedule.title,
        "start_at": schedule.start_at.isoformat(),
        "end_at": schedule.end_at.isoformat(),
        "source": schedule.source,
        "status": schedule.status,
        "linked_task_id": (
            str(schedule.linked_task_id) if schedule.linked_task_id else None
        ),
        "create_time": schedule.create_time.isoformat(),
    }


@router.get("")
async def list_my_schedules(
    db: DB,
    user: CurrentUser,
    status: Annotated[str | None, Query()] = None,
) -> dict:
    """我的日程（时间线/日历拉数）。仅本人；status 可筛 suggested/confirmed 等。"""
    rows = await time_management.list_schedules(db, owner_id=user.id, status=status)
    return ok([_serialize(row) for row in rows])


@router.post("/{schedule_id}/confirm")
async def confirm_my_schedule(schedule_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """确认一条建议态日程使其生效（真人确认，红线）。命中他人 → 404。"""
    return ok(
        _serialize(await time_management.confirm_schedule(db, schedule_id, owner_id=user.id))
    )
