"""个人日程 + 专注番茄钟 HTTP 接口（docs/27-B B2/B4）。

行级隔离：全部按当前登录人 `owner_id`；命中他人 → `ResourceNotFound`(404)。
红线：智能排程只出建议（suggested），`confirm` 才生效（对齐 B2.2）；手动建日程即本人 confirmed。
番茄钟为本人时间治理，非对外触达，不涉红线停点。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.contexts.business.time_management.application.contracts import (
    FocusSessionResult,
    ScheduleResult,
)
from app.contexts.business.time_management.entrypoints import operations as time_management
from app.contexts.business.time_management.entrypoints.operations import SuggestItemInput
from app.platform.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(prefix="/schedules", tags=["schedules"])
focus_router = APIRouter(prefix="/focus", tags=["focus"])

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


def _serialize_focus(focus: FocusSessionResult) -> dict[str, Any]:
    return {
        "id": str(focus.id),
        "start_at": focus.start_at.isoformat(),
        "planned_minutes": focus.planned_minutes,
        "status": focus.status,
        "intercept_notifications": focus.intercept_notifications,
        "ended_at": focus.ended_at.isoformat() if focus.ended_at else None,
        "create_time": focus.create_time.isoformat(),
    }


class ScheduleCreateBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    start_at: datetime
    end_at: datetime
    linked_task_id: uuid.UUID | None = None


class SuggestItemBody(BaseModel):
    ref_task_id: uuid.UUID
    title: str = Field(min_length=1, max_length=200)
    priority: int = 0
    duration_minutes: int = Field(gt=0, le=24 * 60)
    due_at: datetime | None = None


class SuggestBody(BaseModel):
    items: list[SuggestItemBody] = Field(min_length=1, max_length=50)
    window_start: datetime
    window_end: datetime


class FocusStartBody(BaseModel):
    planned_minutes: int = Field(gt=0, le=24 * 60)
    intercept_notifications: bool = True


@router.get("")
async def list_my_schedules(
    db: DB,
    user: CurrentUser,
    status: Annotated[str | None, Query()] = None,
) -> dict:
    """我的日程（时间线/日历拉数）。仅本人；status 可筛 suggested/confirmed 等。"""
    rows = await time_management.list_schedules(db, owner_id=user.id, status=status)
    return ok([_serialize(row) for row in rows])


@router.post("")
async def create_my_schedule(body: ScheduleCreateBody, db: DB, user: CurrentUser) -> dict:
    """手动建一条本人日程（即 confirmed）。个人时间治理，不涉红线。"""
    result = await time_management.create_schedule(
        db,
        owner_id=user.id,
        title=body.title,
        start_at=body.start_at,
        end_at=body.end_at,
        linked_task_id=body.linked_task_id,
    )
    return ok(_serialize(result))


@router.post("/suggest")
async def suggest_my_schedules(body: SuggestBody, db: DB, user: CurrentUser) -> dict:
    """智能排程：按已确认日程为占用、把待排事项塞进窗口空档，落库为建议态（待真人 confirm）。"""
    rows = await time_management.suggest_schedules(
        db,
        owner_id=user.id,
        items=[
            SuggestItemInput(
                ref_task_id=item.ref_task_id,
                title=item.title,
                priority=item.priority,
                duration_minutes=item.duration_minutes,
                due_at=item.due_at,
            )
            for item in body.items
        ],
        window_start=body.window_start,
        window_end=body.window_end,
    )
    return ok([_serialize(row) for row in rows])


@router.post("/{schedule_id}/confirm")
async def confirm_my_schedule(schedule_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """确认一条建议态日程使其生效（真人确认，红线）。命中他人 → 404。"""
    return ok(
        _serialize(await time_management.confirm_schedule(db, schedule_id, owner_id=user.id))
    )


@focus_router.get("/active")
async def my_active_focus(db: DB, user: CurrentUser) -> dict:
    """本人当前进行中的专注会话（供 UI 恢复展示）；无则 data=None。"""
    focus = await time_management.active_focus(db, owner_id=user.id)
    return ok(_serialize_focus(focus) if focus is not None else None)


@focus_router.post("")
async def start_my_focus(body: FocusStartBody, db: DB, user: CurrentUser) -> dict:
    """开始一段专注（番茄钟）。已有进行中会话 → 404（幂等保护）。"""
    result = await time_management.start_focus(
        db,
        owner_id=user.id,
        planned_minutes=body.planned_minutes,
        intercept_notifications=body.intercept_notifications,
    )
    return ok(_serialize_focus(result))


@focus_router.post("/{focus_id}/complete")
async def complete_my_focus(focus_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """完成专注。命中他人/不存在 → 404。"""
    return ok(
        _serialize_focus(await time_management.complete_focus(db, focus_id, owner_id=user.id))
    )


@focus_router.post("/{focus_id}/abort")
async def abort_my_focus(focus_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """放弃专注。命中他人/不存在 → 404。"""
    return ok(
        _serialize_focus(await time_management.abort_focus(db, focus_id, owner_id=user.id))
    )
