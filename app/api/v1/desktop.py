"""真人工作桌面接口（F5a）：本人桌面 + admin 监督他人桌面。

每人只见自己（GET /desktop）；admin 可查他人做监督（GET /desktop/{user_id}）。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import AppError, ok
from app.models.system import SysUser
from app.services import auth_service, desktop_chat_service, desktop_service

router = APIRouter(prefix="/desktop", tags=["desktop"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


class ChatSend(BaseModel):
    """发一条桌面对话消息（可再加最多2个AI圆桌讨论）。"""

    message: str = Field(min_length=1, max_length=4000)
    add_agent_ids: list[uuid.UUID] = Field(default_factory=list, max_length=2)


@router.get("")
async def get_my_desktop(db: DB, user: CurrentUser) -> dict:
    """我的工作桌面（待我处理统一队列 + 我的任务 + 对话/资料入口）。"""
    return ok(await desktop_service.get_desktop(db, user))


@router.get("/chat")
async def get_chat(db: DB, user: CurrentUser) -> dict:
    """我的助理对话（默认助理 + 最近N天历史 + 可加入的AI）。加载时顺带归档超期旧对话。"""
    assistant = await desktop_chat_service.get_or_create_assistant(db, user)
    messages = await desktop_chat_service.list_messages(db, user)
    addable = await desktop_chat_service.list_addable_agents(db, user)
    return ok({
        "assistant": {"id": str(assistant.id), "name": assistant.name},
        "messages": messages,
        "addable_agents": addable,
    })


@router.post("/chat")
async def send_chat(body: ChatSend, db: DB, user: CurrentUser) -> dict:
    """发消息 → 助理（+最多2个被加入AI）圆桌回复 → 返回本轮新增消息。"""
    new_messages = await desktop_chat_service.send(db, user, body.message, body.add_agent_ids)
    return ok({"messages": new_messages})


@router.get("/{user_id}")
async def get_user_desktop(user_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """监督：查看某真人员工的桌面（仅 admin）。不含私人对话。"""
    target = await auth_service.get_user_by_id(db, user_id)
    if target is None or target.is_delete:
        raise AppError("用户不存在", code=404, status_code=404)
    return ok(await desktop_service.get_desktop(db, target))
