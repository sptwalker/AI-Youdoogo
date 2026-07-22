"""真人工作桌面接口（F5a）：本人桌面 + admin 监督他人桌面。

每人只见自己（GET /desktop）；admin 可查他人做监督（GET /desktop/{user_id}）。
"""

import io
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.shared_kernel import PermissionDenied, ResourceNotFound
from app.core.database import get_db
from app.core.sse import sse_response
from app.knowledge import storage
from app.models.deliverable import Deliverable
from app.models.system import SysUser
from app.platform.http_runtime import ok
from app.services import auth_service, deliver_service, desktop_chat_service, desktop_service

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
async def send_chat(body: ChatSend, db: DB, user: CurrentUser) -> StreamingResponse:
    """发消息 → 助理（+最多2个被加入AI）圆桌逐字流式回复（SSE）。"""
    return sse_response(
        desktop_chat_service.send_stream(db, user, body.message, body.add_agent_ids)
    )


@router.get("/deliverables")
async def list_deliverables(
    db: DB,
    user: CurrentUser,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict:
    """我的文件交付区（AI 交付的文档/表格）。admin 可传 user_id 监督他人。"""
    owner_id = user.id
    if user_id is not None and user_id != user.id:
        if user.role_code != "admin":
            raise PermissionDenied("仅管理员可查看他人交付区")
        owner_id = user_id
    return ok(await deliver_service.list_deliverables(db, owner_id))


@router.get("/deliverables/{deliverable_id}/download")
async def download_deliverable(
    deliverable_id: uuid.UUID, db: DB, user: CurrentUser
) -> StreamingResponse:
    """下载一份交付物（仅本人或 admin）。storage_path 去桶前缀取 object key 回读。"""
    row = await db.get(Deliverable, deliverable_id)
    if row is None or row.is_delete:
        raise ResourceNotFound("交付物不存在")
    if row.owner_user_id != user.id and user.role_code != "admin":
        raise PermissionDenied("无权下载该交付物")
    _, _, object_name = row.storage_path.partition("/")  # "bucket/object" → "object"
    data = await storage.get_object_bytes(object_name)
    disposition = f"attachment; filename*=UTF-8''{quote(row.file_name)}"
    return StreamingResponse(
        io.BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@router.get("/{user_id}")
async def get_user_desktop(user_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """监督：查看某真人员工的桌面（仅 admin）。不含私人对话。"""
    target = await auth_service.get_user_by_id(db, user_id)
    if target is None or target.is_delete:
        raise ResourceNotFound("用户不存在")
    return ok(await desktop_service.get_desktop(db, target))
