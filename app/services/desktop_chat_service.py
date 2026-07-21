"""工作桌面对话（专属AI助理 + 持久历史 + 10天归档 + 圆桌多AI）。

- 每个真人一个专属助理（owner_user_id 的 AgentRole），懒创建，附一个 personal KB 作"记忆"。
- 消息持久落 desktop_message；桌面展示最近 N 天；更早的由 archive_old 归档进助理 KB 后硬删。
- 圆桌：发一句话，助理 + 被加入的 AI 按顺序多轮流式发言，后发言者能看到先发言者（限轮数防刷屏）。
复用 run_agent_stream（LLM流式+留痕+知识注入）/ ingest_text（归档入库）/ create_kb（personal 库）。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import run_agent, run_agent_stream
from app.core.exceptions import AppError
from app.core.sse import Event
from app.knowledge.ingest import ingest_text
from app.models.agent import TIER_MEMBER, AgentRole
from app.models.desktop import DesktopMessage
from app.models.knowledge import SCOPE_PERSONAL, KnowledgeBase
from app.models.system import SysUser
from app.services import (
    config_service,
    desktop_chat_repository,
    desktop_chat_streaming,
    knowledge_base_service,
)

logger = logging.getLogger(__name__)

_DEFAULT_HISTORY_DAYS = 10
_DEFAULT_ROUNDS = 2
_MAX_ADD = 2  # 除助理外最多再加 2 个 AI
_MAX_ROUNDS = 3  # 圆桌轮数硬上限（防刷屏/失控）
_RECENT_CONTEXT = 20  # 折进提示词的最近消息条数（控 prompt 体积）

_ASSISTANT_PROMPT = (
    "你是这位同事的专属AI助理，熟悉其工作、乐于协助。回答简明、务实、口吻亲切专业；"
    "遇到需要事实依据的问题优先引用可查资料并标注来源；不确定就说不确定，不编造。"
)


def _display(user: SysUser) -> str:
    return user.real_name or user.username


async def _personal_kb(db: AsyncSession, assistant_id: uuid.UUID) -> KnowledgeBase | None:
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.scope == SCOPE_PERSONAL,
        KnowledgeBase.owner_agent_id == assistant_id,
        KnowledgeBase.is_delete.is_(False),
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def get_or_create_assistant(db: AsyncSession, user: SysUser) -> AgentRole:
    """取或建该真人的专属助理（含其 personal KB 作对话记忆）。幂等。"""
    # 先固化用到的用户字段：rollback 会 expire session 内所有对象，之后再访问 user.* 会触发
    # 同步惰性加载（MissingGreenlet），故提前取出。
    uid, dept, display = user.id, user.department_id, _display(user)
    stmt = select(AgentRole).where(AgentRole.owner_user_id == uid, AgentRole.is_delete.is_(False))
    assistant = (await db.execute(stmt)).scalar_one_or_none()
    if assistant is None:
        # 预查重名再定名，避免 IntegrityError→rollback（rollback 会 expire 整个 session，
        # 连累调用方持有的 user 等对象触发同步惰性加载）。名字仅展示用，撞名加短后缀无碍。
        base_name = f"{display}的助理"
        taken = (
            await db.execute(
                select(AgentRole.id).where(
                    AgentRole.name == base_name, AgentRole.is_delete.is_(False)
                )
            )
        ).first()
        name = f"{base_name}-{uid.hex[:4]}" if taken else base_name
        assistant = AgentRole(
            name=name,
            title="专属助理",
            tier=TIER_MEMBER,
            department_id=dept,
            model_role="daily",
            owner_user_id=uid,
            is_seed=False,
            prompt_template=_ASSISTANT_PROMPT,
        )
        db.add(assistant)
        await db.commit()
        await db.refresh(assistant)
    if await _personal_kb(db, assistant.id) is None:
        await knowledge_base_service.create_kb(
            db,
            name=f"{display}的对话记忆",
            scope=SCOPE_PERSONAL,
            owner_agent_id=assistant.id,
            description="工作桌面归档的历史对话，仅本人助理可检索。",
        )
    return assistant


def _cutoff(days: int) -> datetime:
    return datetime.now(UTC) - timedelta(days=days)


async def _history_days(db: AsyncSession) -> int:
    try:
        return int(await config_service.resolve(db, "desktop_history_days", _DEFAULT_HISTORY_DAYS))
    except (TypeError, ValueError):
        return _DEFAULT_HISTORY_DAYS


def _msg_dict(m: DesktopMessage) -> dict[str, Any]:
    return desktop_chat_repository.message_dict(m)


async def archive_old(db: AsyncSession, user: SysUser, days: int | None = None) -> int:
    """把超过 N 天的旧消息归档进助理 personal KB 后硬删。成功入库才删（失败下次重试）。"""
    days = days if days is not None else await _history_days(db)
    stmt = (
        select(DesktopMessage)
        .where(
            DesktopMessage.owner_user_id == user.id,
            DesktopMessage.create_time < _cutoff(days),
        )
        .order_by(DesktopMessage.create_time)
    )
    old = list((await db.execute(stmt)).scalars())
    if not old:
        return 0
    assistant = await get_or_create_assistant(db, user)
    kb = await _personal_kb(db, assistant.id)
    if kb is None:  # 理论不会（get_or_create 已建），保险
        return 0
    transcript = "\n".join(f"{m.speaker_name}：{m.content}" for m in old)
    span = f"{old[0].create_time:%Y-%m-%d} ~ {old[-1].create_time:%Y-%m-%d}"
    # 结构化分层记忆（H3.2）：先提炼成摘要/事实/实体/偏好再入库（更易检索）；
    # 提炼失败兜底存原始 transcript，绝不丢数据。
    from app.services import memory_service

    distilled = await memory_service.distill_conversation(db, transcript, user_id=user.id)
    if distilled:
        text, title_suffix = distilled, "记忆"
    else:
        text, title_suffix = transcript, "存档"
    try:
        await ingest_text(
            db,
            title=f"{_display(user)}对话{title_suffix} {span}",
            text=text,
            uploader_id=user.id,
            knowledge_base_id=kb.id,
            category="conversation",
        )
    except Exception:  # noqa: BLE001 - 归档失败不删消息，下次重试
        logger.warning("对话归档入库失败 user=%s，保留消息下次重试", user.id, exc_info=True)
        return 0
    ids = [m.id for m in old]
    await db.execute(delete(DesktopMessage).where(DesktopMessage.id.in_(ids)))
    await db.commit()
    return len(ids)


async def list_messages(db: AsyncSession, user: SysUser) -> list[dict[str, Any]]:
    """桌面消息（先归档旧的，再回最近 N 天，升序）。"""
    days = await _history_days(db)
    await archive_old(db, user, days)
    stmt = (
        select(DesktopMessage)
        .where(
            DesktopMessage.owner_user_id == user.id,
            DesktopMessage.create_time >= _cutoff(days),
        )
        .order_by(DesktopMessage.create_time)
    )
    return [_msg_dict(m) for m in (await db.execute(stmt)).scalars()]


async def list_addable_agents(db: AsyncSession, user: SysUser) -> list[dict[str, Any]]:
    """可加入对话的组织 AI（排除所有专属助理）。"""
    stmt = (
        select(AgentRole)
        .where(
            AgentRole.owner_user_id.is_(None),
            AgentRole.is_active.is_(True),
            AgentRole.is_delete.is_(False),
        )
        .order_by(AgentRole.tier, AgentRole.name)
    )
    return [
        {"id": str(a.id), "name": a.name, "title": a.title}
        for a in (await db.execute(stmt)).scalars()
    ]


async def _resolve_participants(
    db: AsyncSession, assistant: AgentRole, add_agent_ids: list[uuid.UUID]
) -> list[AgentRole]:
    """助理 + 被加入的组织 AI（去重、校验、限 2 个）。"""
    seen: set[uuid.UUID] = {assistant.id}
    participants = [assistant]
    for aid in add_agent_ids:
        if aid in seen:
            continue
        agent = await db.get(AgentRole, aid)
        if (
            agent is None
            or agent.is_delete
            or not agent.is_active
            or agent.owner_user_id is not None
        ):
            raise AppError("要加入的 AI 不存在或不可用", code=404, status_code=404)
        seen.add(aid)
        participants.append(agent)
    return participants


async def send_stream(
    db: AsyncSession, user: SysUser, message: str, add_agent_ids: list[uuid.UUID]
) -> AsyncIterator[Event]:
    runtime = desktop_chat_streaming.DesktopChatRuntime(
        get_assistant=get_or_create_assistant,
        resolve_participants=_resolve_participants,
        display_user=_display,
        agent_stream=run_agent_stream,
        agent_runner=run_agent,
    )
    async for event in desktop_chat_streaming.send_stream(
        db,
        user,
        message,
        add_agent_ids,
        runtime=runtime,
        default_rounds=_DEFAULT_ROUNDS,
        max_add=_MAX_ADD,
        max_rounds=_MAX_ROUNDS,
        recent_context=_RECENT_CONTEXT,
    ):
        yield event


_try_orchestrate = desktop_chat_streaming.try_orchestrate
_progress_text = desktop_chat_streaming.progress_text
_emit_orchestration = desktop_chat_streaming.emit_orchestration
