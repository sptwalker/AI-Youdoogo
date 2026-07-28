"""协作空间接口（F3'）：频道 + 消息流 + @Agent 触发 + 升格。

读（频道列表/消息流）任意登录；发言任意登录（@Agent 成本护栏在 service）；
建/归档频道、升格 需 admin/executive。
"""

import io
import uuid
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.business.group_messaging.entrypoints import operations
from app.core.sse import sse_response
from app.platform.database import get_db
from app.platform.http_runtime import ok
from app.schemas.discussion import ChannelCreate, MessagePost, PromoteRequest

router = APIRouter(prefix="/channels", tags=["discussion"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[Any, Depends(require_roles("admin", "executive"))]


@router.post("/attachments")
async def upload_attachment(db: DB, user: CurrentUser, file: Annotated[UploadFile, File()]) -> dict:
    """上传群聊附件（图片/文件，I6）→ MinIO → 返回附件元数据供发消息带上。"""
    return ok(
        await operations.upload_attachment(
            db,
            name=file.filename or "未命名",
            content=await file.read(),
            content_type=file.content_type or "application/octet-stream",
        )
    )


@router.get("/attachments/download")
async def download_attachment(
    storage_path: Annotated[str, Query()],
    name: Annotated[str, Query()],
    db: DB,
    user: CurrentUser,
) -> StreamingResponse:
    """下载群聊附件（storage_path=bucket/object，I6）。"""
    result = await operations.download_attachment(
        db,
        storage_path=storage_path,
        name=name,
        user_id=user.id,
    )
    return StreamingResponse(
        io.BytesIO(result.content),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(result.name)}"},
    )


@router.get("")
async def list_channels(
    db: DB,
    user: CurrentUser,
    department_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict:
    """频道列表（普通用户仅本人群，管理角色可做全局管理）。"""
    return ok(
        await operations.list_channels(
            db,
            department_id=department_id,
            principal_id=user.id,
            principal_role=user.role_code,
        )
    )


@router.post("")
async def create_channel(body: ChannelCreate, db: DB, user: CurrentUser) -> dict:
    """新建讨论群（任意登录用户可建群；创建者自动入群，可带初始成员 I4）。"""
    channel = await operations.create_channel(
        db,
        name=body.name,
        department_id=body.department_id,
        creator_id=user.id,
        creator_name=user.real_name or user.username,
        default_agent_id=body.default_agent_id,
        members=[m.model_dump() for m in body.members],
    )
    return ok({"id": str(channel.id), "name": channel.name})


@router.get("/realtime/stream")
async def realtime_stream(db: DB, user: CurrentUser) -> StreamingResponse:
    """实时消息订阅流（SSE，I3）：订阅用户可见群频道，别人发言即时推送到本连接。

    这是"服务端主动推送"——A 发言 B/C 不刷新即收到（Redis pub/sub 跨 worker 广播）。
    """
    return sse_response(operations.subscribe_user_messages(db, user.id))


@router.get("/mine")
async def my_channels(db: DB, user: CurrentUser) -> dict:
    """我的群列表 + 每群未读数（I5，话题页签用）。"""
    return ok(await operations.my_channels_with_unread(db, user.id))


@router.post("/{channel_id}/read")
async def mark_read(channel_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """把某群未读清零（进群/读消息时调，I5）。"""
    await operations.mark_read(db, channel_id, user.id)
    return ok()


@router.get("/{channel_id}/members")
async def list_members(channel_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """群成员名单（I4）。"""
    return ok(await operations.list_members(db, channel_id, member_id=user.id))


@router.post("/{channel_id}/members")
async def add_members(channel_id: uuid.UUID, body: dict, db: DB, user: CurrentUser) -> dict:
    """群主加成员。body: {members: [{member_type, member_id, member_name}]}。"""
    n = await operations.add_members(
        db,
        channel_id,
        body.get("members") or [],
        owner_id=user.id,
    )
    return ok({"added": n})


@router.delete("/{channel_id}/members/{member_type}/{member_id}")
async def remove_member(
    channel_id: uuid.UUID, member_type: str, member_id: uuid.UUID, db: DB, user: CurrentUser
) -> dict:
    """踢出成员（仅群主）。不能踢群主自己。"""
    await operations.remove_member(
        db,
        channel_id,
        member_type,
        member_id,
        owner_id=user.id,
    )
    return ok()


@router.delete("/{channel_id}")
async def disband_channel(channel_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """解散讨论群（仅群主）：归档入 KB 后软删频道 + 全部成员。"""
    await operations.disband_channel(db, channel_id, owner_id=user.id)
    return ok()


@router.post("/{channel_id}/archive")
async def archive_channel(channel_id: uuid.UUID, db: DB, _: Manager) -> dict:
    """归档频道。"""
    channel = await operations.archive_channel(db, channel_id)
    return ok({"id": str(channel.id), "is_archived": channel.is_archived})


@router.get("/{channel_id}/messages")
async def list_messages(
    channel_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """频道消息流。"""
    return ok(
        await operations.list_messages(
            db,
            channel_id,
            limit=limit,
            member_id=user.id,
        )
    )


@router.post("/{channel_id}/messages")
async def post_message(
    channel_id: uuid.UUID, body: MessagePost, db: DB, user: CurrentUser
) -> StreamingResponse:
    """发言（@ 的 AI 顾问逐个逐字流式回复，SSE）。"""
    await operations.ensure_member_access(db, channel_id, user.id)
    return sse_response(
        operations.post_message_stream(
            db,
            channel_id,
            speaker_id=user.id,
            speaker_name=user.real_name or user.username,
            content=body.content,
            mentioned_agent_ids=body.mentioned_agent_ids,
            attachments=body.attachments,
            require_member_id=user.id,
        )
    )


# 升格挂在 /messages/{id} 下（跨频道操作单条消息）
message_router = APIRouter(prefix="/messages", tags=["discussion"])


@message_router.post("/{message_id}/promote")
async def promote_message(
    message_id: uuid.UUID, body: PromoteRequest, db: DB, manager: Manager
) -> dict:
    """把消息升格为提案/任务（红线：产出仍走真人确认闸门）。"""
    return ok(
        await operations.promote_message(db, message_id, target=body.target, creator_id=manager.id)
    )
