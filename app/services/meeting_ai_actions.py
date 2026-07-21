"""AI speech, advisory votes, minutes, and resolution-to-task actions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import get_agent_role, run_agent, run_agent_stream
from app.agents.contracts import ExecutionContext
from app.agents.skills import execute_all, fold_notes
from app.core.exceptions import AppError
from app.core.sse import Event
from app.models.agent import AgentTaskRecord
from app.models.meeting import (
    IN_PROGRESS,
    MeetingDiscuss,
    MeetingInfo,
    MeetingResolution,
    MeetingVote,
)
from app.models.task import TaskCard
from app.schemas.meeting import DiscussOut
from app.services import task_service

EXPERT_NAME = "会商AI专家"
VALID_CHOICES = ("approve", "reject", "abstain")


async def _get_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> MeetingInfo:
    meeting = await db.get(MeetingInfo, meeting_id)
    if meeting is None or meeting.is_delete:
        raise AppError("会议不存在", code=404, status_code=404)
    return meeting


def _require_in_progress(meeting: MeetingInfo) -> None:
    if meeting.status != IN_PROGRESS:
        raise AppError(f"会议当前状态 {meeting.status}，需先开始（in_progress）")


async def _list_discussions(
    db: AsyncSession, meeting_id: uuid.UUID
) -> list[MeetingDiscuss]:
    stmt = (
        select(MeetingDiscuss)
        .where(MeetingDiscuss.meeting_id == meeting_id)
        .order_by(MeetingDiscuss.create_time)
    )
    return list((await db.execute(stmt)).scalars())


async def ai_expert_speak_stream(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    topic: str,
    operator_id: uuid.UUID | None = None,
) -> AsyncIterator[Event]:
    meeting = await _get_meeting(db, meeting_id)
    _require_in_progress(meeting)
    role = await get_agent_role(db, EXPERT_NAME)
    if role is None:
        raise AppError("未配置会商AI专家角色，请先执行数据库迁移（alembic upgrade head）")

    history = await _list_discussions(db, meeting_id)
    context = "\n".join(f"{item.speaker_name}：{item.content}" for item in history)
    context = context or "（暂无发言）"
    user_message = (
        f"这是一场决策会议，议题：{topic}\n\n已有发言：\n{context}\n\n"
        "请以会商AI专家身份发表一段简明分析意见（利弊、风险、建议），供与会真人参考。"
    )
    yield ("message_start", {"speaker_agent_id": str(role.id), "speaker_name": role.name})
    record: AgentTaskRecord | None = None
    async for item in run_agent_stream(
        db,
        role,
        task_type="meeting_discuss",
        input_summary=f"会议发言：{topic[:40]}",
        user_message=user_message,
        user_id=operator_id,
    ):
        if isinstance(item, AgentTaskRecord):
            record = item
        else:
            yield ("delta", {"text": item})
    assert record is not None
    content = record.output_content or record.error_msg or "（无产出）"
    result = await execute_all(
        db,
        role,
        content,
        user_id=operator_id,
        execution_context=ExecutionContext(
            user_id=operator_id,
            agent_runner=run_agent,
        ),
    )
    content = fold_notes(content, result)
    discussion = MeetingDiscuss(
        meeting_id=meeting_id,
        speaker_type="ai",
        speaker_id=role.id,
        speaker_name=role.name,
        content=content,
    )
    db.add(discussion)
    await db.commit()
    await db.refresh(discussion)
    yield ("message_end", DiscussOut.model_validate(discussion).model_dump(mode="json"))

    for consulted, consult_record in result.consult_replies:
        answer = consult_record.output_content or consult_record.error_msg or "（无回应）"
        yield (
            "message_start",
            {"speaker_agent_id": str(consulted.id), "speaker_name": consulted.name},
        )
        yield ("delta", {"text": answer})
        consulted_discussion = MeetingDiscuss(
            meeting_id=meeting_id,
            speaker_type="ai",
            speaker_id=consulted.id,
            speaker_name=consulted.name,
            content=answer,
        )
        db.add(consulted_discussion)
        await db.commit()
        await db.refresh(consulted_discussion)
        yield (
            "message_end",
            DiscussOut.model_validate(consulted_discussion).model_dump(mode="json"),
        )


def parse_choice(text: str) -> str:
    lines = (text or "").strip().splitlines()
    first = lines[0].lower().lstrip("*# \t-—：:") if lines else ""
    for choice in VALID_CHOICES:
        if first.startswith(choice):
            return choice
    return "abstain"


async def ai_expert_vote(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    subject: str,
    operator_id: uuid.UUID | None = None,
) -> MeetingVote:
    meeting = await _get_meeting(db, meeting_id)
    _require_in_progress(meeting)
    role = await get_agent_role(db, EXPERT_NAME)
    if role is None:
        raise AppError("未配置会商AI专家角色，请先执行数据库迁移（alembic upgrade head）")
    record = await run_agent(
        db,
        role,
        task_type="meeting_vote",
        input_summary=f"AI参考票：{subject[:40]}",
        user_message=(
            f"就以下表决事项给出你的参考意见：{subject}\n"
            "第一行只输出 approve / reject / abstain 之一，第二行给一句理由。"
        ),
        user_id=operator_id,
    )
    vote = MeetingVote(
        meeting_id=meeting_id,
        subject=subject,
        voter_type="ai",
        voter_id=role.id,
        choice=parse_choice(record.output_content or ""),
        comment=record.output_content,
    )
    db.add(vote)
    await db.commit()
    await db.refresh(vote)
    return vote


async def generate_minutes(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    operator_id: uuid.UUID | None = None,
) -> MeetingInfo:
    meeting = await _get_meeting(db, meeting_id)
    discussions = await _list_discussions(db, meeting_id)
    if not discussions:
        raise AppError("会议暂无发言，无法生成纪要")
    role = await get_agent_role(db, EXPERT_NAME)
    if role is None:
        raise AppError("未配置会商AI专家角色，请先执行数据库迁移（alembic upgrade head）")
    body = "\n".join(
        f"{item.speaker_name}（{item.speaker_type}）：{item.content}"
        for item in discussions
    )
    record = await run_agent(
        db,
        role,
        task_type="meeting_minutes",
        input_summary=f"会议纪要：{meeting.title[:40]}",
        user_message=(
            f"会议主题：{meeting.title}\n\n以下是全部发言，请生成结构化会议纪要"
            f"（含【议题】【主要观点】【分歧点】【建议决议】）：\n\n{body}"
        ),
        user_id=operator_id,
    )
    meeting.summary = record.output_content or record.error_msg or "（无产出）"
    await db.commit()
    await db.refresh(meeting)
    return meeting


async def resolution_to_task(
    db: AsyncSession,
    resolution_id: uuid.UUID,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None = None,
) -> TaskCard:
    resolution = await db.get(MeetingResolution, resolution_id)
    if resolution is None or resolution.is_delete:
        raise AppError("决议不存在", code=404, status_code=404)
    if not resolution.is_confirmed:
        raise AppError("决议未经真人确认，不可转任务卡（决议须真人确认生效）")
    if resolution.converted_task_id is not None:
        raise AppError("该决议已转过任务卡")
    task = await task_service.create_task(
        db,
        title=f"[会议决议] {resolution.content[:60]}",
        task_type="resolution_execution",
        creator_id=creator_id,
        assignee_agent_id=assignee_agent_id,
        payload={"resolution_id": str(resolution.id)},
    )
    resolution.converted_task_id = task.id
    await db.commit()
    return task
