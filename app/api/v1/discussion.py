"""协作空间接口（F3'）：频道 + 消息流 + @Agent 触发 + 升格。

读（频道列表/消息流）任意登录；发言任意登录（@Agent 成本护栏在 service）；
建/归档频道、升格 需 admin/executive。
"""

import io
import uuid
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.shared_kernel import InvalidInput, PermissionDenied, RuleViolation
from app.core.database import get_db
from app.core.sse import sse_response
from app.knowledge import storage
from app.models.discussion import (
    MEMBER_HUMAN,
    ChannelMember,
    DiscussionChannel,
    DiscussionMessage,
)
from app.models.system import SysUser
from app.platform.http_runtime import ok
from app.schemas.discussion import ChannelCreate, MessagePost, PromoteRequest
from app.services import discussion_service

router = APIRouter(prefix="/channels", tags=["discussion"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[SysUser, Depends(require_roles("admin", "executive"))]

_MAX_ATTACH_BYTES = 20 * 1024 * 1024  # 单附件 20MB 上限
_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")
_MANAGER_ROLES = {"admin", "executive"}


async def _require_channel_member(
    db: AsyncSession, channel_id: uuid.UUID, user: SysUser
) -> None:
    """校验频道存在且当前真人是有效成员。"""
    await discussion_service.get_channel(db, channel_id)
    if not await discussion_service.is_member(db, channel_id, user.id):
        raise PermissionDenied("仅群成员可访问")


async def _can_download_attachment(
    db: AsyncSession, storage_path: str, user_id: uuid.UUID
) -> bool:
    """附件必须已挂在当前用户可访问群的一条有效消息上。"""
    stmt = (
        select(DiscussionMessage.attachments)
        .join(DiscussionChannel, DiscussionChannel.id == DiscussionMessage.channel_id)
        .join(ChannelMember, ChannelMember.channel_id == DiscussionMessage.channel_id)
        .where(
            DiscussionMessage.is_delete.is_(False),
            DiscussionChannel.is_delete.is_(False),
            ChannelMember.member_type == MEMBER_HUMAN,
            ChannelMember.member_id == user_id,
            ChannelMember.is_delete.is_(False),
        )
    )
    attachment_groups = (await db.execute(stmt)).scalars()
    return any(
        isinstance(attachment, dict) and attachment.get("storage_path") == storage_path
        for attachments in attachment_groups
        for attachment in (attachments or [])
    )


@router.post("/attachments")
async def upload_attachment(
    db: DB, user: CurrentUser, file: Annotated[UploadFile, File()]
) -> dict:
    """上传群聊附件（图片/文件，I6）→ MinIO → 返回附件元数据供发消息带上。"""
    content = await file.read()
    if len(content) > _MAX_ATTACH_BYTES:
        raise RuleViolation(f"文件过大（>{_MAX_ATTACH_BYTES // 1024 // 1024}MB）")
    name = file.filename or "未命名"
    is_image = name.lower().endswith(_IMAGE_EXT)
    object_name = f"chat/{uuid.uuid4().hex}/{name}"
    storage_path = await storage.put_object(
        object_name, content, file.content_type or "application/octet-stream"
    )
    return ok({
        "type": "image" if is_image else "file",
        "name": name, "storage_path": storage_path, "size": len(content),
    })


@router.get("/attachments/download")
async def download_attachment(
    storage_path: Annotated[str, Query()],
    name: Annotated[str, Query()],
    db: DB,
    user: CurrentUser,
) -> StreamingResponse:
    """下载群聊附件（storage_path=bucket/object，I6）。"""
    _, _, object_name = storage_path.partition("/")
    if not object_name.startswith("chat/"):  # 限定只能下群聊附件，防越权读任意对象
        raise InvalidInput("非法附件路径")
    if not await _can_download_attachment(db, storage_path, user.id):
        raise PermissionDenied("无权访问该附件")
    data = await storage.get_object_bytes(object_name)
    return StreamingResponse(
        io.BytesIO(data), media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"},
    )


@router.get("")
async def list_channels(
    db: DB,
    user: CurrentUser,
    department_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict:
    """频道列表（普通用户仅本人群，管理角色可做全局管理）。"""
    channels = await discussion_service.list_channels(db, department_id=department_id)
    if user.role_code in _MANAGER_ROLES:
        return ok(channels)
    member_channel_ids = set(await discussion_service.my_channel_ids(db, user.id))
    return ok([channel for channel in channels if channel["id"] in member_channel_ids])


@router.post("")
async def create_channel(body: ChannelCreate, db: DB, user: CurrentUser) -> dict:
    """新建讨论群（任意登录用户可建群；创建者自动入群，可带初始成员 I4）。"""
    c = await discussion_service.create_channel(
        db, name=body.name, department_id=body.department_id,
        creator_id=user.id, creator_name=user.real_name or user.username,
        default_agent_id=body.default_agent_id,
        members=[m.model_dump() for m in body.members],
    )
    return ok({"id": str(c.id), "name": c.name})


@router.get("/realtime/stream")
async def realtime_stream(db: DB, user: CurrentUser) -> StreamingResponse:
    """实时消息订阅流（SSE，I3）：订阅用户可见群频道，别人发言即时推送到本连接。

    这是"服务端主动推送"——A 发言 B/C 不刷新即收到（Redis pub/sub 跨 worker 广播）。
    """
    from app.core.database import async_session_factory
    from app.services import realtime_service

    channel_ids = await discussion_service.my_channel_ids(db, user.id)  # 仅订阅我所在的群

    async def _still_member(channel_id: str) -> bool:
        try:
            parsed_channel_id = uuid.UUID(channel_id)
        except ValueError:
            return False
        async with async_session_factory() as membership_db:
            return await discussion_service.is_member(
                membership_db, parsed_channel_id, user.id
            )

    return sse_response(
        realtime_service.subscribe(channel_ids, authorize=_still_member)
    )


@router.get("/mine")
async def my_channels(db: DB, user: CurrentUser) -> dict:
    """我的群列表 + 每群未读数（I5，话题页签用）。"""
    return ok(await discussion_service.my_channels_with_unread(db, user.id))


@router.post("/{channel_id}/read")
async def mark_read(channel_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """把某群未读清零（进群/读消息时调，I5）。"""
    await _require_channel_member(db, channel_id, user)
    await discussion_service.mark_read(db, channel_id, user.id)
    return ok()


@router.get("/{channel_id}/members")
async def list_members(channel_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """群成员名单（I4）。"""
    await _require_channel_member(db, channel_id, user)
    return ok(await discussion_service.list_members(db, channel_id))


@router.post("/{channel_id}/members")
async def add_members(channel_id: uuid.UUID, body: dict, db: DB, user: CurrentUser) -> dict:
    """群主加成员。body: {members: [{member_type, member_id, member_name}]}。"""
    if not await discussion_service.is_owner(db, channel_id, user.id):
        raise PermissionDenied("仅群主可添加成员")
    n = await discussion_service.add_members(db, channel_id, body.get("members") or [])
    return ok({"added": n})


@router.delete("/{channel_id}/members/{member_type}/{member_id}")
async def remove_member(
    channel_id: uuid.UUID, member_type: str, member_id: uuid.UUID, db: DB, user: CurrentUser
) -> dict:
    """踢出成员（仅群主）。不能踢群主自己。"""
    if not await discussion_service.is_owner(db, channel_id, user.id):
        raise PermissionDenied("仅群主可踢出成员")
    if member_type == "human" and await discussion_service.is_owner(db, channel_id, member_id):
        raise InvalidInput("不能踢出群主")
    await discussion_service.remove_member(db, channel_id, member_type, member_id)
    return ok()


@router.delete("/{channel_id}")
async def disband_channel(channel_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """解散讨论群（仅群主）：归档入 KB 后软删频道 + 全部成员。"""
    if not await discussion_service.is_owner(db, channel_id, user.id):
        raise PermissionDenied("仅群主可解散讨论群")
    await discussion_service.disband_channel(db, channel_id)
    return ok()


@router.post("/{channel_id}/archive")
async def archive_channel(channel_id: uuid.UUID, db: DB, _: Manager) -> dict:
    """归档频道。"""
    c = await discussion_service.archive_channel(db, channel_id)
    return ok({"id": str(c.id), "is_archived": c.is_archived})


@router.get("/{channel_id}/messages")
async def list_messages(
    channel_id: uuid.UUID,
    db: DB,
    user: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """频道消息流。"""
    await _require_channel_member(db, channel_id, user)
    return ok(await discussion_service.list_messages(db, channel_id, limit=limit))


@router.post("/{channel_id}/messages")
async def post_message(
    channel_id: uuid.UUID, body: MessagePost, db: DB, user: CurrentUser
) -> StreamingResponse:
    """发言（@ 的 AI 顾问逐个逐字流式回复，SSE）。"""
    await _require_channel_member(db, channel_id, user)
    return sse_response(
        discussion_service.post_message_stream(
            db, channel_id,
            speaker_id=user.id, speaker_name=user.real_name or user.username,
            content=body.content, mentioned_agent_ids=body.mentioned_agent_ids,
            attachments=body.attachments,
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
        await discussion_service.promote_message(
            db, message_id, target=body.target, creator_id=manager.id
        )
    )
