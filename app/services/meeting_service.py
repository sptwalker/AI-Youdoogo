"""会议会商业务逻辑（阶段4 下半场）。

覆盖 docs/06 阶段4：会中 AI 专家参与讨论、投票（真人/AI 区分）、自动会议纪要、
决议转任务卡。红线（docs/04）：决议须真人确认（confirm）才生效，仅确认后可转任务卡；
AI 票仅参考，真人票决定。
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

if TYPE_CHECKING:
    from app.models.system import SysUser

from app.agents.base import get_agent_role, run_agent, run_agent_stream
from app.agents.contracts import ExecutionContext
from app.agents.skills import execute_all, fold_notes
from app.core.exceptions import AppError
from app.core.sse import Event
from app.models.agent import AgentTaskRecord
from app.models.meeting import (
    CLOSED,
    IN_PROGRESS,
    SCHEDULED,
    MeetingDiscuss,
    MeetingInfo,
    MeetingResolution,
    MeetingVote,
)
from app.models.task import TaskCard
from app.schemas.meeting import DiscussOut
from app.services import task_service

EXPERT_NAME = "会商AI专家"  # 与 alembic 007 种子行一致
_VALID_CHOICES = ("approve", "reject", "abstain")
_MEETING_TRANSITIONS: dict[str, frozenset[str]] = {
    SCHEDULED: frozenset({IN_PROGRESS, CLOSED}),
    IN_PROGRESS: frozenset({CLOSED}),
    CLOSED: frozenset(),
}


async def get_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> MeetingInfo:
    m = await db.get(MeetingInfo, meeting_id)
    if m is None or m.is_delete:
        raise AppError("会议不存在", code=404, status_code=404)
    return m


async def create_meeting(
    db: AsyncSession,
    *,
    title: str,
    creator_id: uuid.UUID,
    meeting_type: str = "decision",
    participants: list[dict[str, Any]] | None = None,
    department_id: uuid.UUID | None = None,
) -> MeetingInfo:
    """创建会议（初始 scheduled）。"""
    m = MeetingInfo(
        title=title, creator_id=creator_id, meeting_type=meeting_type,
        participants=participants or [], department_id=department_id,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def set_status(db: AsyncSession, meeting_id: uuid.UUID, to_status: str) -> MeetingInfo:
    """会议状态流转（scheduled→in_progress→closed）。"""
    m = await get_meeting(db, meeting_id)
    if to_status not in _MEETING_TRANSITIONS.get(m.status, frozenset()):
        raise AppError(f"非法会议状态流转：{m.status} → {to_status}")
    m.status = to_status
    await db.commit()
    await db.refresh(m)
    return m


def _require_in_progress(m: MeetingInfo) -> None:
    if m.status != IN_PROGRESS:
        raise AppError(f"会议当前状态 {m.status}，需先开始（in_progress）")


async def add_discussion(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    speaker_id: uuid.UUID | None,
    speaker_name: str,
    content: str,
) -> MeetingDiscuss:
    """真人发言。"""
    m = await get_meeting(db, meeting_id)
    _require_in_progress(m)
    d = MeetingDiscuss(
        meeting_id=meeting_id, speaker_type="human",
        speaker_id=speaker_id, speaker_name=speaker_name, content=content,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    return d


async def ai_expert_speak_stream(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    topic: str,
    operator_id: uuid.UUID | None = None,
) -> AsyncIterator[Event]:
    """会中 AI 专家就议题流式发言（message_start → delta* → message_end），产出留痕并写入会议讨论。

    Raises:
        AppError: 会议未开始 / 未配置会商专家角色（经 sse_response 转 error 事件）。
    """
    m = await get_meeting(db, meeting_id)
    _require_in_progress(m)
    role = await get_agent_role(db, EXPERT_NAME)
    if role is None:
        raise AppError("未配置会商AI专家角色，请先执行数据库迁移（alembic upgrade head）")

    history = await list_discussions(db, meeting_id)
    ctx = "\n".join(f"{d.speaker_name}：{d.content}" for d in history) or "（暂无发言）"
    user_message = (
        f"这是一场决策会议，议题：{topic}\n\n已有发言：\n{ctx}\n\n"
        f"请以会商AI专家身份发表一段简明分析意见（利弊、风险、建议），供与会真人参考。"
    )
    yield ("message_start", {"speaker_agent_id": str(role.id), "speaker_name": role.name})
    record: AgentTaskRecord | None = None
    async for item in run_agent_stream(
        db, role,
        task_type="meeting_discuss",
        input_summary=f"会议发言：{topic[:40]}",
        user_message=user_message,
        user_id=operator_id,
    ):
        if isinstance(item, AgentTaskRecord):
            record = item
        else:
            yield ("delta", {"text": item})
    assert record is not None  # run_agent_stream 末项必为记录
    content = record.output_content or record.error_msg or "（无产出）"
    # 协作原语（docs/13 §10）：先执行指令、注记折进正文，再落库
    proto = await execute_all(
        db,
        role,
        content,
        user_id=operator_id,
        execution_context=ExecutionContext(
            user_id=operator_id,
            agent_runner=run_agent,
        ),
    )
    content = fold_notes(content, proto)
    d = MeetingDiscuss(
        meeting_id=meeting_id, speaker_type="ai", speaker_id=role.id,
        speaker_name=role.name, content=content,
    )
    db.add(d)
    await db.commit()
    await db.refresh(d)
    yield ("message_end", DiscussOut.model_validate(d).model_dump(mode="json"))
    # 被咨询 AI 的答复作为独立会议发言追加
    for consulted, rec in proto.consult_replies:
        answer = rec.output_content or rec.error_msg or "（无回应）"
        yield (
            "message_start",
            {"speaker_agent_id": str(consulted.id), "speaker_name": consulted.name},
        )
        yield ("delta", {"text": answer})
        c = MeetingDiscuss(
            meeting_id=meeting_id, speaker_type="ai", speaker_id=consulted.id,
            speaker_name=consulted.name, content=answer,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        yield ("message_end", DiscussOut.model_validate(c).model_dump(mode="json"))


async def cast_vote(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    subject: str,
    voter_type: str,
    voter_id: uuid.UUID | None,
    choice: str,
    comment: str | None = None,
) -> MeetingVote:
    """投票。voter_type=human/ai（红线：AI 票仅参考）。"""
    if choice not in _VALID_CHOICES:
        raise AppError(f"choice 仅支持 {'/'.join(_VALID_CHOICES)}")
    if voter_type not in ("human", "ai"):
        raise AppError("voter_type 仅支持 human/ai")
    m = await get_meeting(db, meeting_id)
    _require_in_progress(m)
    v = MeetingVote(
        meeting_id=meeting_id, subject=subject, voter_type=voter_type,
        voter_id=voter_id, choice=choice, comment=comment,
    )
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


def _parse_choice(text: str) -> str:
    """从模型首行解析表决建议，兜底 abstain。

    要求 approve/reject/abstain 出现在首行开头（剥离前导非字母如 * 空格），避免
    “我不建议 approve”这类否定句被子串命中而误判。
    """
    lines = (text or "").strip().splitlines()
    first = lines[0].lower().lstrip("*# \t-—：:") if lines else ""
    for c in _VALID_CHOICES:
        if first.startswith(c):
            return c
    return "abstain"


async def ai_expert_vote(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    subject: str,
    operator_id: uuid.UUID | None = None,
) -> MeetingVote:
    """会商AI专家对表决对象给出参考票（红线：AI 票仅参考，不替代真人决定）。"""
    m = await get_meeting(db, meeting_id)
    _require_in_progress(m)
    role = await get_agent_role(db, EXPERT_NAME)
    if role is None:
        raise AppError("未配置会商AI专家角色，请先执行数据库迁移（alembic upgrade head）")
    user_message = (
        f"就以下表决事项给出你的参考意见：{subject}\n"
        f"第一行只输出 approve / reject / abstain 之一，第二行给一句理由。"
    )
    record = await run_agent(
        db, role,
        task_type="meeting_vote",
        input_summary=f"AI参考票：{subject[:40]}",
        user_message=user_message,
        user_id=operator_id,
    )
    choice = _parse_choice(record.output_content or "")
    return await cast_vote(
        db, meeting_id, subject=subject, voter_type="ai", voter_id=role.id,
        choice=choice, comment=record.output_content,
    )


async def tally_votes(db: AsyncSession, meeting_id: uuid.UUID, subject: str) -> dict[str, Any]:
    """统计某表决对象的票型，区分真人票与 AI 票（红线：以真人票为准）。"""
    stmt = (
        select(MeetingVote.voter_type, MeetingVote.choice, func.count())
        .where(MeetingVote.meeting_id == meeting_id, MeetingVote.subject == subject)
        .group_by(MeetingVote.voter_type, MeetingVote.choice)
    )
    rows = (await db.execute(stmt)).all()
    tally: dict[str, dict[str, int]] = {"human": {}, "ai": {}}
    for voter_type, choice, cnt in rows:
        tally.setdefault(voter_type, {})[choice] = int(cnt)
    human = tally.get("human", {})
    passed = human.get("approve", 0) > human.get("reject", 0)
    return {
        "subject": subject, "human": human, "ai": tally.get("ai", {}),
        "human_passed": passed,  # 仅供参考，最终以决议真人确认为准
    }


async def generate_minutes(
    db: AsyncSession, meeting_id: uuid.UUID, *, operator_id: uuid.UUID | None = None
) -> MeetingInfo:
    """基于全部发言生成会议纪要，写入 meeting.summary。

    Raises:
        AppError: 无发言可纪要 / 未配置会商专家角色。
    """
    m = await get_meeting(db, meeting_id)
    discussions = await list_discussions(db, meeting_id)
    if not discussions:
        raise AppError("会议暂无发言，无法生成纪要")
    role = await get_agent_role(db, EXPERT_NAME)
    if role is None:
        raise AppError("未配置会商AI专家角色，请先执行数据库迁移（alembic upgrade head）")

    body = "\n".join(f"{d.speaker_name}（{d.speaker_type}）：{d.content}" for d in discussions)
    user_message = (
        f"会议主题：{m.title}\n\n以下是全部发言，请生成结构化会议纪要"
        f"（含【议题】【主要观点】【分歧点】【建议决议】）：\n\n{body}"
    )
    record = await run_agent(
        db, role,
        task_type="meeting_minutes",
        input_summary=f"会议纪要：{m.title[:40]}",
        user_message=user_message,
        user_id=operator_id,
    )
    m.summary = record.output_content or record.error_msg or "（无产出）"
    await db.commit()
    await db.refresh(m)
    return m


async def create_resolution(
    db: AsyncSession,
    meeting_id: uuid.UUID,
    *,
    content: str,
    owner_id: uuid.UUID | None = None,
    due_date: date | None = None,
) -> MeetingResolution:
    """登记决议（默认未确认，需真人 confirm 才生效）。"""
    await get_meeting(db, meeting_id)
    r = MeetingResolution(
        meeting_id=meeting_id, content=content, owner_id=owner_id, due_date=due_date,
    )
    db.add(r)
    await db.commit()
    await db.refresh(r)
    return r


async def confirm_resolution(
    db: AsyncSession, resolution_id: uuid.UUID, *, confirmed_by: uuid.UUID
) -> MeetingResolution:
    """真人确认决议生效（红线：决议须真人确认后才生效）。"""
    r = await db.get(MeetingResolution, resolution_id)
    if r is None or r.is_delete:
        raise AppError("决议不存在", code=404, status_code=404)
    r.is_confirmed = True
    r.confirmed_by = confirmed_by
    await db.commit()
    await db.refresh(r)
    return r


async def resolution_to_task(
    db: AsyncSession,
    resolution_id: uuid.UUID,
    *,
    creator_id: uuid.UUID,
    assignee_agent_id: uuid.UUID | None = None,
) -> TaskCard:
    """把已确认决议转为任务卡（红线：仅 is_confirmed 决议可转）。

    Raises:
        AppError: 决议未确认 / 已转过。
    """
    r = await db.get(MeetingResolution, resolution_id)
    if r is None or r.is_delete:
        raise AppError("决议不存在", code=404, status_code=404)
    if not r.is_confirmed:
        raise AppError("决议未经真人确认，不可转任务卡（决议须真人确认生效）")
    if r.converted_task_id is not None:
        raise AppError("该决议已转过任务卡")
    task = await task_service.create_task(
        db,
        title=f"[会议决议] {r.content[:60]}",
        task_type="resolution_execution",
        creator_id=creator_id,
        assignee_agent_id=assignee_agent_id,
        payload={"resolution_id": str(r.id)},
    )
    r.converted_task_id = task.id
    await db.commit()
    return task


async def list_discussions(db: AsyncSession, meeting_id: uuid.UUID) -> list[MeetingDiscuss]:
    stmt = (
        select(MeetingDiscuss)
        .where(MeetingDiscuss.meeting_id == meeting_id)
        .order_by(MeetingDiscuss.create_time)
    )
    return list((await db.execute(stmt)).scalars())


async def list_resolutions(db: AsyncSession, meeting_id: uuid.UUID) -> list[MeetingResolution]:
    stmt = (
        select(MeetingResolution)
        .where(MeetingResolution.meeting_id == meeting_id)
        .order_by(MeetingResolution.create_time)
    )
    return list((await db.execute(stmt)).scalars())


async def list_meetings(
    db: AsyncSession, *, status: str | None = None, limit: int = 100,
    viewer: SysUser | None = None,
) -> list[MeetingInfo]:
    stmt = select(MeetingInfo).where(MeetingInfo.is_delete.is_(False))
    if status:
        stmt = stmt.where(MeetingInfo.status == status)
    if viewer is not None:  # 行级可见性（H1.2）
        from app.services import permission_service

        cond = permission_service.row_filter(MeetingInfo, viewer)
        if cond is not None:
            stmt = stmt.where(cond)
    return list(
        (await db.execute(stmt.order_by(MeetingInfo.create_time.desc()).limit(limit))).scalars()
    )
