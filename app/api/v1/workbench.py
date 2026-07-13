"""真人工作台接口（F3）：聚合「待我确认」三队列。只读，任意登录用户可看。

动作（验收/评审/确认）仍走各自既有端点（tasks/proposals/meetings），各自 gate 权限。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.core.exceptions import ok
from app.services import workbench_service

router = APIRouter(prefix="/workbench", tags=["workbench"])

DB = Annotated[AsyncSession, Depends(get_db)]


@router.get("")
async def get_workbench(db: DB, _: CurrentUser) -> dict:
    """待我处理：待验收任务 / 待评审提案 / 待确认决议 + 计数。"""
    return ok(await workbench_service.get_pending(db))
