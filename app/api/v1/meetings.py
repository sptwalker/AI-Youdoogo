"""会议会商接口：会议生命周期 + 讨论（含AI专家）+ 投票（真人/AI）+ 纪要 + 决议转任务卡。

创建/流转/发言/投票需登录；纪要与 AI 参与需 admin/executive。
红线（docs/04）：决议须真人确认（confirm）才生效，仅确认后可转任务卡。
"""

import uuid
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.business.meeting_management.entrypoints import operations
from app.contexts.foundations.governance.audit_trail.public import (
    AppendAuditRecordCommand,
    append_audit_record,
)
from app.core.sse import sse_response
from app.platform.database import get_db
from app.platform.http_runtime import ok
from app.schemas.meeting import (
    AiSpeakRequest,
    AiVoteRequest,
    ConvertRequest,
    DiscussOut,
    DiscussRequest,
    MeetingCreate,
    MeetingOut,
    ResolutionCreate,
    ResolutionOut,
    StatusRequest,
    VoteOut,
    VoteRequest,
)
from app.schemas.task import TaskOut

router = APIRouter(prefix="/meetings", tags=["meetings"])

DB = Annotated[AsyncSession, Depends(get_db)]


class RequestUser(operations.PrincipalSource, Protocol):
    @property
    def real_name(self) -> str: ...

    @property
    def username(self) -> str: ...


Manager = Annotated[RequestUser, Depends(require_roles("admin", "executive"))]


@router.post("")
async def create_meeting(body: MeetingCreate, db: DB, user: CurrentUser) -> dict:
    """创建会议。"""
    m = await operations.create_meeting(
        db,
        title=body.title,
        creator_id=user.id,
        meeting_type=body.meeting_type,
        participants=body.participants,
    )
    return ok(MeetingOut.model_validate(m).model_dump(mode="json"))


@router.get("")
async def list_meetings(
    db: DB,
    user: CurrentUser,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """会议列表（行级可见性：普通员工只见本人/本部门，管理层全见）。"""
    ms = await operations.list_meetings(
        db,
        status=status,
        limit=limit,
        principal=operations.principal_from_user(user),
    )
    return ok([MeetingOut.model_validate(m).model_dump(mode="json") for m in ms])


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """会议详情 + 发言 + 决议（行级可见性守卫）。"""
    detail = await operations.get_meeting_detail(
        db,
        meeting_id,
        principal=operations.principal_from_user(user),
    )
    return ok(
        {
            "meeting": MeetingOut.model_validate(detail.meeting).model_dump(mode="json"),
            "discussions": [
                DiscussOut.model_validate(d).model_dump(mode="json") for d in detail.discussions
            ],
            "resolutions": [
                ResolutionOut.model_validate(r).model_dump(mode="json") for r in detail.resolutions
            ],
        }
    )


@router.post("/{meeting_id}/status")
async def set_status(meeting_id: uuid.UUID, body: StatusRequest, db: DB, _: Manager) -> dict:
    """会议开始/结束（scheduled→in_progress→closed）。"""
    m = await operations.set_status(db, meeting_id, body.to_status)
    return ok(MeetingOut.model_validate(m).model_dump(mode="json"))


@router.post("/{meeting_id}/discuss")
async def add_discussion(
    meeting_id: uuid.UUID, body: DiscussRequest, db: DB, user: CurrentUser
) -> dict:
    """真人发言。"""
    d = await operations.add_discussion(
        db,
        meeting_id,
        speaker_id=user.id,
        speaker_name=user.real_name or user.username,
        content=body.content,
    )
    return ok(DiscussOut.model_validate(d).model_dump(mode="json"))


@router.post("/{meeting_id}/ai-speak")
async def ai_speak(
    meeting_id: uuid.UUID, body: AiSpeakRequest, db: DB, manager: Manager
) -> StreamingResponse:
    """会中 AI 专家就议题逐字流式发言（SSE，参考意见）。"""
    return sse_response(
        operations.ai_expert_speak_stream(db, meeting_id, topic=body.topic, operator_id=manager.id)
    )


@router.post("/{meeting_id}/vote")
async def cast_vote(meeting_id: uuid.UUID, body: VoteRequest, db: DB, user: CurrentUser) -> dict:
    """真人投票。"""
    v = await operations.cast_vote(
        db,
        meeting_id,
        subject=body.subject,
        voter_type="human",
        voter_id=user.id,
        choice=body.choice,
        comment=body.comment,
    )
    return ok(VoteOut.model_validate(v).model_dump(mode="json"))


@router.post("/{meeting_id}/ai-vote")
async def ai_vote(meeting_id: uuid.UUID, body: AiVoteRequest, db: DB, manager: Manager) -> dict:
    """会商AI专家给出参考票（AI 票仅参考）。"""
    v = await operations.ai_expert_vote(
        db, meeting_id, subject=body.subject, operator_id=manager.id
    )
    return ok(VoteOut.model_validate(v).model_dump(mode="json"))


@router.get("/{meeting_id}/tally")
async def tally(
    meeting_id: uuid.UUID, subject: Annotated[str, Query()], db: DB, _: CurrentUser
) -> dict:
    """票型统计（区分真人/AI 票，以真人票为准）。"""
    return ok(await operations.tally_votes(db, meeting_id, subject))


@router.get("/{meeting_id}/vote-subjects")
async def vote_subjects(meeting_id: uuid.UUID, db: DB, _: CurrentUser) -> dict:
    """已有表决对象列表（供前端统计下拉，避免手打精确匹配，P1-8）。"""
    return ok(list(await operations.list_vote_subjects(db, meeting_id)))


@router.post("/{meeting_id}/minutes")
async def generate_minutes(meeting_id: uuid.UUID, db: DB, manager: Manager) -> dict:
    """自动生成会议纪要。"""
    m = await operations.generate_minutes(db, meeting_id, operator_id=manager.id)
    return ok(MeetingOut.model_validate(m).model_dump(mode="json"))


@router.post("/{meeting_id}/resolutions")
async def create_resolution(
    meeting_id: uuid.UUID, body: ResolutionCreate, db: DB, _: Manager
) -> dict:
    """登记决议（默认未确认）。"""
    r = await operations.create_resolution(
        db,
        meeting_id,
        content=body.content,
        owner_id=body.owner_id,
        due_date=body.due_date,
    )
    return ok(ResolutionOut.model_validate(r).model_dump(mode="json"))


@router.post("/resolutions/{resolution_id}/confirm")
async def confirm_resolution(resolution_id: uuid.UUID, db: DB, manager: Manager) -> dict:
    """真人确认决议生效（红线）。"""
    r = await operations.confirm_resolution(
        db,
        resolution_id,
        principal=operations.principal_from_user(manager),
    )
    await append_audit_record(
        db,
        AppendAuditRecordCommand(
            actor_id=manager.id,
            actor_role=manager.role_code,
            action="meeting.resolution.confirm",
            summary=f"决议确认生效 {r.content[:40]}",
            target_type="meeting_resolution",
            target_id=r.id,
        ),
    )
    return ok(ResolutionOut.model_validate(r).model_dump(mode="json"))


@router.post("/resolutions/{resolution_id}/convert")
async def convert_resolution(
    resolution_id: uuid.UUID, body: ConvertRequest, db: DB, manager: Manager
) -> dict:
    """把已确认决议转为任务卡。"""
    task = await operations.resolution_to_task(
        db, resolution_id, creator_id=manager.id, assignee_agent_id=body.assignee_agent_id
    )
    await append_audit_record(
        db,
        AppendAuditRecordCommand(
            actor_id=manager.id,
            actor_role=manager.role_code,
            action="meeting.resolution.convert",
            summary=f"决议转任务卡 {task.title[:40]}",
            target_type="task_card",
            target_id=task.id,
        ),
    )
    return ok(TaskOut.model_validate(task).model_dump(mode="json"))
