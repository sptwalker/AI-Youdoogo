"""真人工作桌面接口（F5a）：本人桌面 + admin 监督他人桌面。

每人只见自己（GET /desktop）；admin 可查他人做监督（GET /desktop/{user_id}）。
"""

import io
import uuid
from typing import Annotated, Protocol
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.business.assistant_conversations.application.contracts import (
    Principal,
    SendMessageCommand,
)
from app.contexts.business.assistant_conversations.entrypoints import (
    operations as assistant_conversations,
)
from app.contexts.business.work_desktop import public as work_desktop
from app.contexts.foundations.identity.application.contracts import IdentityUserResult
from app.core.sse import sse_response
from app.platform.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(prefix="/desktop", tags=["desktop"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[IdentityUserResult, Depends(require_roles("admin"))]


class _UserLike(Protocol):
    @property
    def id(self) -> uuid.UUID: ...

    @property
    def username(self) -> str: ...

    @property
    def real_name(self) -> str: ...

    @property
    def role_code(self) -> str: ...

    @property
    def department_id(self) -> uuid.UUID | None: ...


class ChatSend(BaseModel):
    """发一条桌面对话消息（可再加最多2个AI圆桌讨论）。"""

    message: str = Field(min_length=1, max_length=4000)
    add_agent_ids: list[uuid.UUID] = Field(default_factory=list, max_length=2)
    reply_to_message_id: uuid.UUID | None = None
    attachments: list[dict[str, object]] = Field(default_factory=list)


class _MessagePin(BaseModel):
    message_id: uuid.UUID


class _InboxItemRef(BaseModel):
    kind: str = Field(max_length=16)
    id: uuid.UUID


class _InboxMark(BaseModel):
    """批量置收件箱读态（真人逐条/一次确认）。至少给一个动作。"""

    items: list[_InboxItemRef] = Field(min_length=1, max_length=200)
    is_read: bool | None = None
    is_processed: bool | None = None


def _conversation_principal(user: _UserLike) -> Principal:
    return Principal(
        id=user.id,
        display_name=user.real_name or user.username,
        department_id=user.department_id,
    )


def _desktop_principal(user: _UserLike) -> work_desktop.DesktopPrincipal:
    return work_desktop.DesktopPrincipal(
        id=user.id,
        display_name=user.real_name or user.username,
        role_code=user.role_code,
        department_id=user.department_id,
    )


@router.get("")
async def get_my_desktop(db: DB, user: CurrentUser) -> dict:
    """我的工作桌面（待我处理统一队列 + 我的任务 + 对话/资料入口）。"""
    return ok(await work_desktop.get_desktop(db, _desktop_principal(user)))


@router.post("/inbox/mark")
async def mark_inbox(body: _InboxMark, db: DB, user: CurrentUser) -> dict:
    """批量置收件箱读/处理态（真人确认触发）。仅改本人读态，不触碰来源、不外发（红线）。"""
    return ok(
        await work_desktop.mark_inbox(
            db,
            _desktop_principal(user),
            tuple(work_desktop.InboxItemRef(kind=item.kind, id=item.id) for item in body.items),
            is_read=body.is_read,
            is_processed=body.is_processed,
        )
    )


@router.get("/chat")
async def get_chat(db: DB, user: CurrentUser) -> dict:
    """我的助理对话（默认助理 + 最近N天历史 + 可加入的AI）。加载时顺带归档超期旧对话。"""
    return ok(await assistant_conversations.get_conversation(db, _conversation_principal(user)))


@router.post("/chat")
async def send_chat(body: ChatSend, db: DB, user: CurrentUser) -> StreamingResponse:
    """发消息 → 助理（+最多2个被加入AI）圆桌逐字流式回复（SSE）。"""
    return sse_response(
        assistant_conversations.send_message_stream(
            db,
            SendMessageCommand(
                principal=_conversation_principal(user),
                message=body.message,
                add_agent_ids=tuple(body.add_agent_ids),
                reply_to_message_id=body.reply_to_message_id,
                attachments=tuple(dict(value) for value in body.attachments),
            ),
        )
    )


@router.post("/chat/attachments")
async def upload_chat_attachment(
    db: DB,
    user: CurrentUser,
    file: Annotated[UploadFile, File()],
) -> dict:
    """上传桌面对话附件（图片/文件）→ MinIO → 返回附件元数据供发消息带上。"""
    return ok(
        await assistant_conversations.upload_attachment(
            db,
            name=file.filename or "未命名",
            content=await file.read(),
            content_type=file.content_type or "application/octet-stream",
        )
    )


@router.get("/chat/attachments/download")
async def download_chat_attachment(
    storage_path: Annotated[str, Query()],
    name: Annotated[str, Query()],
    db: DB,
    user: CurrentUser,
) -> StreamingResponse:
    """下载桌面对话附件（storage_path=bucket/object）。"""
    result = await assistant_conversations.download_attachment(
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


@router.post("/chat/pin")
async def pin_chat_message(body: _MessagePin, db: DB, user: CurrentUser) -> dict:
    """置顶本人桌面对话中的一条消息。"""
    return ok(
        await assistant_conversations.pin_message(
            db,
            owner_user_id=user.id,
            message_id=body.message_id,
            pinned_by_user_id=user.id,
        )
    )


@router.post("/chat/unpin")
async def unpin_chat_message(body: _MessagePin, db: DB, user: CurrentUser) -> dict:
    """取消置顶本人桌面对话中的一条消息。"""
    return ok(
        await assistant_conversations.unpin_message(
            db,
            owner_user_id=user.id,
            message_id=body.message_id,
        )
    )


@router.get("/deliverables")
async def list_deliverables(
    db: DB,
    user: CurrentUser,
    user_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict:
    """我的文件交付区（AI 交付的文档/表格）。admin 可传 user_id 监督他人。"""
    return ok(
        await work_desktop.list_deliverables(
            db,
            _desktop_principal(user),
            requested_owner_id=user_id,
        )
    )


@router.get("/deliverables/{deliverable_id}/download")
async def download_deliverable(
    deliverable_id: uuid.UUID, db: DB, user: CurrentUser
) -> StreamingResponse:
    """下载一份交付物（仅本人或 admin）。storage_path 去桶前缀取 object key 回读。"""
    result = await work_desktop.download_deliverable(
        db,
        _desktop_principal(user),
        deliverable_id,
    )
    disposition = f"attachment; filename*=UTF-8''{quote(result.file_name)}"
    return StreamingResponse(
        io.BytesIO(result.content),
        media_type="application/octet-stream",
        headers={"Content-Disposition": disposition},
    )


@router.get("/{user_id}")
async def get_user_desktop(user_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """监督：查看某真人员工的桌面（仅 admin）。不含私人对话。"""
    return ok(
        await work_desktop.get_supervised_desktop(
            db,
            _desktop_principal(admin),
            user_id,
        )
    )
