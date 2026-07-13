"""协作空间业务逻辑（docs/13 F3'）：频道 CRUD + 消息流 + @Agent 触发 + 升格。

@Agent 成本护栏五件套（docs/13 决策⑦）：
1. 无 @ 不调 AI；2. 显式点名触发一次；3. 单条 fan-out ≤3 且去重；
4. 禁 AI 互@（只有真人消息触发 AI，AI 回复 mentioned=[] 不回环）；
5. 预算走 run_agent 内既有 record_usage 日预算护栏。
红线：AI 发言仅参考；升格产出（提案/任务）仍走既有真人确认闸门。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent
from app.core.exceptions import AppError
from app.models.agent import AgentRole
from app.models.discussion import (
    SPEAKER_AI,
    SPEAKER_HUMAN,
    DiscussionChannel,
    DiscussionMessage,
)
from app.services import proposal_service, task_service

MAX_FANOUT = 3  # 护栏3：单条消息最多触发 3 个 AI
_CONTEXT_N = 20  # 拼给 AI 的近期消息条数
_PROMOTE_TARGETS = ("proposal", "task")


def _dedup(ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """保序去重（护栏3）。"""
    seen: list[uuid.UUID] = []
    for i in ids:
        if i not in seen:
            seen.append(i)
    return seen


def _channel_dict(c: DiscussionChannel) -> dict[str, Any]:
    return {
        "id": str(c.id), "name": c.name,
        "department_id": str(c.department_id) if c.department_id else None,
        "default_agent_id": str(c.default_agent_id) if c.default_agent_id else None,
        "is_archived": c.is_archived, "create_time": c.create_time.isoformat(),
    }


def _msg_dict(m: DiscussionMessage) -> dict[str, Any]:
    return {
        "id": str(m.id), "channel_id": str(m.channel_id), "speaker_type": m.speaker_type,
        "speaker_id": str(m.speaker_id) if m.speaker_id else None, "speaker_name": m.speaker_name,
        "content": m.content, "mentioned_agent_ids": m.mentioned_agent_ids,
        "ai_source_record_id": str(m.ai_source_record_id) if m.ai_source_record_id else None,
        "ref_type": m.ref_type, "ref_id": str(m.ref_id) if m.ref_id else None,
        "create_time": m.create_time.isoformat(),
    }


async def get_channel(db: AsyncSession, channel_id: uuid.UUID) -> DiscussionChannel:
    c = await db.get(DiscussionChannel, channel_id)
    if c is None or c.is_delete:
        raise AppError("讨论频道不存在", code=404, status_code=404)
    return c


async def create_channel(
    db: AsyncSession,
    *,
    name: str,
    department_id: uuid.UUID | None = None,
    creator_id: uuid.UUID | None = None,
    default_agent_id: uuid.UUID | None = None,
) -> DiscussionChannel:
    c = DiscussionChannel(
        name=name, department_id=department_id,
        creator_id=creator_id, default_agent_id=default_agent_id,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def list_channels(
    db: AsyncSession, *, department_id: uuid.UUID | None = None
) -> list[dict[str, Any]]:
    stmt = select(DiscussionChannel).where(DiscussionChannel.is_delete.is_(False))
    if department_id is not None:
        stmt = stmt.where(DiscussionChannel.department_id == department_id)
    stmt = stmt.order_by(DiscussionChannel.create_time)
    return [_channel_dict(c) for c in (await db.execute(stmt)).scalars()]


async def archive_channel(db: AsyncSession, channel_id: uuid.UUID) -> DiscussionChannel:
    c = await get_channel(db, channel_id)
    c.is_archived = True
    await db.commit()
    await db.refresh(c)
    return c


async def list_messages(
    db: AsyncSession, channel_id: uuid.UUID, *, limit: int = 100
) -> list[dict[str, Any]]:
    """频道最近 limit 条消息（按时间正序返回）。"""
    stmt = (
        select(DiscussionMessage)
        .where(DiscussionMessage.channel_id == channel_id)
        .order_by(DiscussionMessage.create_time.desc())  # 先取最近 limit 条
        .limit(limit)
    )
    rows = list((await db.execute(stmt)).scalars())
    return [_msg_dict(m) for m in reversed(rows)]  # 再倒回正序展示/喂 AI


async def post_message(
    db: AsyncSession,
    channel_id: uuid.UUID,
    *,
    speaker_id: uuid.UUID | None,
    speaker_name: str,
    content: str,
    mentioned_agent_ids: list[uuid.UUID],
) -> dict[str, Any]:
    """真人发言；@ 的 AI 顾问逐个触发一次回复（成本护栏五件套）。"""
    channel = await get_channel(db, channel_id)
    if channel.is_archived:
        raise AppError("频道已归档，不可发言")

    human = DiscussionMessage(
        channel_id=channel_id, speaker_type=SPEAKER_HUMAN, speaker_id=speaker_id,
        speaker_name=speaker_name, content=content,
        mentioned_agent_ids=[str(a) for a in mentioned_agent_ids],
    )
    db.add(human)
    await db.commit()
    await db.refresh(human)

    targets = _dedup(mentioned_agent_ids)[:MAX_FANOUT]  # 护栏 1(空则不进循环)/2/3
    # 频道近期上下文取一次（含刚发的这条），循环内复用——避免每个 @agent 重查（N+1）
    ctx = "（暂无发言）"
    if targets:
        history = await list_messages(db, channel_id, limit=_CONTEXT_N)
        ctx = "\n".join(f"{h['speaker_name']}：{h['content']}" for h in history) or ctx
    ai_msgs: list[dict[str, Any]] = []
    for agent_id in targets:
        role = await db.get(AgentRole, agent_id)
        if role is None or role.is_delete or not role.is_active:
            continue  # 坏 @ 不阻断整条发言
        user_message = (
            f"你在企业协作频道「{channel.name}」中被 @ 点名。\n\n"
            f"频道近期讨论：\n{ctx}\n\n"
            f"请以你的角色身份，就上文给出一段简明的参考意见/建议（仅供真人参考）。"
        )
        record = await run_agent(
            db, role, task_type="discussion_reply",
            input_summary=f"讨论回复：{content[:40]}",
            user_message=user_message, user_id=speaker_id,
        )
        ai = DiscussionMessage(
            channel_id=channel_id, speaker_type=SPEAKER_AI, speaker_id=role.id,
            speaker_name=role.name,
            content=record.output_content or record.error_msg or "（无产出）",
            ai_source_record_id=record.id, mentioned_agent_ids=[],  # 护栏4：AI 不 @人，不回环
        )
        db.add(ai)
        await db.commit()
        await db.refresh(ai)
        ai_msgs.append(_msg_dict(ai))

    return {"human": _msg_dict(human), "ai": ai_msgs}


async def promote_message(
    db: AsyncSession,
    message_id: uuid.UUID,
    *,
    target: str,
    creator_id: uuid.UUID,
) -> dict[str, Any]:
    """把一条讨论消息升格为提案/任务，回填 ref 溯源（红线：产出仍走真人确认）。"""
    if target not in _PROMOTE_TARGETS:
        raise AppError(f"target 仅支持 {'/'.join(_PROMOTE_TARGETS)}")
    msg = await db.get(DiscussionMessage, message_id)
    if msg is None or msg.is_delete:
        raise AppError("消息不存在", code=404, status_code=404)
    if msg.ref_id is not None:
        raise AppError("该消息已升格过")

    title = msg.content[:60] or "讨论升格"
    if target == "proposal":
        p = await proposal_service.create_proposal(
            db, title=title, background=msg.content, plan="（讨论升格，方案待补充）",
            creator_id=creator_id,
        )
        ref_id = p.id
    else:  # task
        t = await task_service.create_task(
            db, title=title, task_type="manual", creator_id=creator_id,
            payload={"from_message_id": str(msg.id)},
        )
        ref_id = t.id

    msg.ref_type = target
    msg.ref_id = ref_id
    await db.commit()
    return {"ref_type": target, "ref_id": str(ref_id)}
