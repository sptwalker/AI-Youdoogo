"""会议会商接口：会议生命周期 + 讨论（含AI专家）+ 投票（真人/AI）+ 纪要 + 决议转任务卡。

创建/流转/发言/投票需登录；纪要与 AI 参与需 admin/executive。
红线（docs/04）：决议须真人确认（confirm）才生效，仅确认后可转任务卡。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import ok
from app.models.system import SysUser
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
from app.services import meeting_service

router = APIRouter(prefix="/meetings", tags=["meetings"])

DB = Annotated[AsyncSession, Depends(get_db)]
Manager = Annotated[SysUser, Depends(require_roles("admin", "executive"))]


@router.post("")
async def create_meeting(body: MeetingCreate, db: DB, user: CurrentUser) -> dict:
    """创建会议。"""
    m = await meeting_service.create_meeting(
        db, title=body.title, creator_id=user.id,
        meeting_type=body.meeting_type, participants=body.participants,
    )
    return ok(MeetingOut.model_validate(m).model_dump(mode="json"))


@router.get("")
async def list_meetings(
    db: DB,
    _: CurrentUser,
    status: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """会议列表（默认最多 100 条）。"""
    ms = await meeting_service.list_meetings(db, status=status, limit=limit)
    return ok([MeetingOut.model_validate(m).model_dump(mode="json") for m in ms])


@router.get("/{meeting_id}")
async def get_meeting(meeting_id: uuid.UUID, db: DB, _: CurrentUser) -> dict:
    """会议详情 + 发言 + 决议。"""
    m = await meeting_service.get_meeting(db, meeting_id)
    discussions = await meeting_service.list_discussions(db, meeting_id)
    resolutions = await meeting_service.list_resolutions(db, meeting_id)
    return ok(
        {
            "meeting": MeetingOut.model_validate(m).model_dump(mode="json"),
            "discussions": [
                DiscussOut.model_validate(d).model_dump(mode="json") for d in discussions
            ],
            "resolutions": [
                ResolutionOut.model_validate(r).model_dump(mode="json") for r in resolutions
            ],
        }
    )


@router.post("/{meeting_id}/status")
async def set_status(meeting_id: uuid.UUID, body: StatusRequest, db: DB, _: Manager) -> dict:
    """会议开始/结束（scheduled→in_progress→closed）。"""
    m = await meeting_service.set_status(db, meeting_id, body.to_status)
    return ok(MeetingOut.model_validate(m).model_dump(mode="json"))


@router.post("/{meeting_id}/discuss")
async def add_discussion(
    meeting_id: uuid.UUID, body: DiscussRequest, db: DB, user: CurrentUser
) -> dict:
    """真人发言。"""
    d = await meeting_service.add_discussion(
        db, meeting_id, speaker_id=user.id,
        speaker_name=user.real_name or user.username, content=body.content,
    )
    return ok(DiscussOut.model_validate(d).model_dump(mode="json"))


@router.post("/{meeting_id}/ai-speak")
async def ai_speak(meeting_id: uuid.UUID, body: AiSpeakRequest, db: DB, manager: Manager) -> dict:
    """会中 AI 专家就议题发言（参考意见）。"""
    d = await meeting_service.ai_expert_speak(
        db, meeting_id, topic=body.topic, operator_id=manager.id
    )
    return ok(DiscussOut.model_validate(d).model_dump(mode="json"))


@router.post("/{meeting_id}/vote")
async def cast_vote(meeting_id: uuid.UUID, body: VoteRequest, db: DB, user: CurrentUser) -> dict:
    """真人投票。"""
    v = await meeting_service.cast_vote(
        db, meeting_id, subject=body.subject, voter_type="human",
        voter_id=user.id, choice=body.choice, comment=body.comment,
    )
    return ok(VoteOut.model_validate(v).model_dump(mode="json"))


@router.post("/{meeting_id}/ai-vote")
async def ai_vote(meeting_id: uuid.UUID, body: AiVoteRequest, db: DB, manager: Manager) -> dict:
    """会商AI专家给出参考票（AI 票仅参考）。"""
    v = await meeting_service.ai_expert_vote(
        db, meeting_id, subject=body.subject, operator_id=manager.id
    )
    return ok(VoteOut.model_validate(v).model_dump(mode="json"))


@router.get("/{meeting_id}/tally")
async def tally(
    meeting_id: uuid.UUID, subject: Annotated[str, Query()], db: DB, _: CurrentUser
) -> dict:
    """票型统计（区分真人/AI 票，以真人票为准）。"""
    return ok(await meeting_service.tally_votes(db, meeting_id, subject))


@router.post("/{meeting_id}/minutes")
async def generate_minutes(meeting_id: uuid.UUID, db: DB, manager: Manager) -> dict:
    """自动生成会议纪要。"""
    m = await meeting_service.generate_minutes(db, meeting_id, operator_id=manager.id)
    return ok(MeetingOut.model_validate(m).model_dump(mode="json"))


@router.post("/{meeting_id}/resolutions")
async def create_resolution(
    meeting_id: uuid.UUID, body: ResolutionCreate, db: DB, _: Manager
) -> dict:
    """登记决议（默认未确认）。"""
    r = await meeting_service.create_resolution(
        db, meeting_id, content=body.content, owner_id=body.owner_id, due_date=body.due_date,
    )
    return ok(ResolutionOut.model_validate(r).model_dump(mode="json"))


@router.post("/resolutions/{resolution_id}/confirm")
async def confirm_resolution(resolution_id: uuid.UUID, db: DB, manager: Manager) -> dict:
    """真人确认决议生效（红线）。"""
    r = await meeting_service.confirm_resolution(db, resolution_id, confirmed_by=manager.id)
    return ok(ResolutionOut.model_validate(r).model_dump(mode="json"))


@router.post("/resolutions/{resolution_id}/convert")
async def convert_resolution(
    resolution_id: uuid.UUID, body: ConvertRequest, db: DB, manager: Manager
) -> dict:
    """把已确认决议转为任务卡。"""
    task = await meeting_service.resolution_to_task(
        db, resolution_id, creator_id=manager.id, assignee_agent_id=body.assignee_agent_id
    )
    return ok(TaskOut.model_validate(task).model_dump(mode="json"))
