"""协作空间接口（F3'）：频道 + 消息流 + @Agent 触发 + 升格。

读（频道列表/消息流）任意登录；发言任意登录（@Agent 成本护栏在 service）；
建/归档频道、升格 需 admin/executive。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import ok
from app.core.sse import sse_response
from app.models.system import SysUser
from app.schemas.discussion import ChannelCreate, MessagePost, PromoteRequest
from app.services import discussion_service

router = APIRouter(prefix="/channels", tags=["discussion"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[SysUser, Depends(require_roles("admin", "executive"))]


@router.get("")
async def list_channels(
    db: DB,
    _: CurrentUser,
    department_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict:
    """频道列表（可按部门过滤）。"""
    return ok(await discussion_service.list_channels(db, department_id=department_id))


@router.post("")
async def create_channel(body: ChannelCreate, db: DB, user: CurrentUser) -> dict:
    """新建讨论群（任意登录用户可建群；创建者自动入群，可带初始成员 I4）。"""
    c = await discussion_service.create_channel(
        db, name=body.name, department_id=body.department_id,
        creator_id=user.id, default_agent_id=body.default_agent_id,
        members=[m.model_dump() for m in body.members],
    )
    return ok({"id": str(c.id), "name": c.name})


@router.get("/realtime/stream")
async def realtime_stream(db: DB, user: CurrentUser) -> StreamingResponse:
    """实时消息订阅流（SSE，I3）：订阅用户可见群频道，别人发言即时推送到本连接。

    这是"服务端主动推送"——A 发言 B/C 不刷新即收到（Redis pub/sub 跨 worker 广播）。
    """
    from app.services import realtime_service

    channel_ids = await discussion_service.my_channel_ids(db, user.id)  # 仅订阅我所在的群
    return sse_response(realtime_service.subscribe(channel_ids))


@router.get("/{channel_id}/members")
async def list_members(channel_id: uuid.UUID, db: DB, _: CurrentUser) -> dict:
    """群成员名单（I4）。"""
    return ok(await discussion_service.list_members(db, channel_id))


@router.post("/{channel_id}/members")
async def add_members(channel_id: uuid.UUID, body: dict, db: DB, _: CurrentUser) -> dict:
    """加成员（真人+AI 混合，I4）。body: {members: [{member_type, member_id, member_name}]}。"""
    n = await discussion_service.add_members(db, channel_id, body.get("members") or [])
    return ok({"added": n})


@router.delete("/{channel_id}/members/{member_type}/{member_id}")
async def remove_member(
    channel_id: uuid.UUID, member_type: str, member_id: uuid.UUID, db: DB, _: CurrentUser
) -> dict:
    """移除成员（I4）。"""
    await discussion_service.remove_member(db, channel_id, member_type, member_id)
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
    _: CurrentUser,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """频道消息流。"""
    return ok(await discussion_service.list_messages(db, channel_id, limit=limit))


@router.post("/{channel_id}/messages")
async def post_message(
    channel_id: uuid.UUID, body: MessagePost, db: DB, user: CurrentUser
) -> StreamingResponse:
    """发言（@ 的 AI 顾问逐个逐字流式回复，SSE）。"""
    return sse_response(
        discussion_service.post_message_stream(
            db, channel_id,
            speaker_id=user.id, speaker_name=user.real_name or user.username,
            content=body.content, mentioned_agent_ids=body.mentioned_agent_ids,
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
