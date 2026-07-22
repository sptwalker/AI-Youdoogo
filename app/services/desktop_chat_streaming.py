"""Desktop chat SSE, roundtable execution, and orchestration progress emission."""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext
from app.agents.skills import execute_all, fold_notes
from app.contexts.shared_kernel import RuleViolation
from app.core.sse import Event
from app.models.agent import AgentRole, AgentTaskRecord
from app.models.desktop import SPEAKER_AI, SPEAKER_USER
from app.models.system import SysUser
from app.services import config_service, desktop_chat_repository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DesktopChatRuntime:
    """Small injected port set that keeps the streaming module independently testable."""

    get_assistant: Callable[[AsyncSession, SysUser], Awaitable[AgentRole]]
    resolve_participants: Callable[
        [AsyncSession, AgentRole, list[uuid.UUID]], Awaitable[list[AgentRole]]
    ]
    display_user: Callable[[SysUser], str]
    agent_stream: Callable[..., AsyncIterator[str | AgentTaskRecord]]
    agent_runner: Callable[..., Awaitable[AgentTaskRecord]]


def _transcript(conversation: list[tuple[str, str]]) -> str:
    return "\n".join(f"{name}：{content}" for name, content in conversation)


async def send_stream(
    db: AsyncSession,
    user: SysUser,
    message: str,
    add_agent_ids: list[uuid.UUID],
    *,
    runtime: DesktopChatRuntime,
    default_rounds: int,
    max_add: int,
    max_rounds: int,
    recent_context: int,
) -> AsyncIterator[Event]:
    """Persist and stream one user message through orchestration or an AI roundtable."""
    if len(set(add_agent_ids)) > max_add:
        raise RuleViolation(f"最多再加入 {max_add} 个 AI")
    assistant = await runtime.get_assistant(db, user)
    participants = await runtime.resolve_participants(db, assistant, add_agent_ids)

    rounds = default_rounds
    try:
        rounds = int(
            await config_service.resolve(db, "desktop_roundtable_rounds", default_rounds)
        )
    except (TypeError, ValueError):
        pass
    rounds = max(1, min(rounds, max_rounds))
    if len(participants) == 1:
        rounds = 1

    conversation = [
        (item.speaker_name, item.content)
        for item in await desktop_chat_repository.recent_window(
            db, user, limit=recent_context
        )
    ]
    user_name = runtime.display_user(user)
    user_message = await desktop_chat_repository.save_message(
        db,
        owner_user_id=user.id,
        speaker_type=SPEAKER_USER,
        speaker_name=user_name,
        content=message,
    )
    conversation.append((user_name, message))
    yield ("message_end", desktop_chat_repository.message_dict(user_message))

    if len(participants) == 1:
        snapshot = await try_orchestrate(db, user, assistant, message)
        if snapshot is not None:
            async for event in emit_orchestration(db, user, assistant, snapshot):
                yield event
            return

    for _round in range(rounds):
        for agent in participants:
            others = "、".join(item.name for item in participants if item.id != agent.id)
            hint = (
                f"以下是圆桌对话记录：\n{_transcript(conversation)}\n\n"
                f"请以「{agent.name}」的身份，结合以上讨论"
                + (f"（在座还有{others}）" if others else "")
                + "简明发表你的看法，不要重复他人已说过的内容。"
            )
            yield (
                "message_start",
                {"speaker_agent_id": str(agent.id), "speaker_name": agent.name},
            )
            record: AgentTaskRecord | None = None
            async for item in runtime.agent_stream(
                db,
                agent,
                task_type="desktop_chat",
                input_summary=f"桌面对话：{message[:40]}",
                user_message=hint,
                user_id=user.id,
                use_knowledge=True,
            ):
                if isinstance(item, AgentTaskRecord):
                    record = item
                else:
                    yield ("delta", {"text": item})
            assert record is not None
            reply = record.output_content or record.error_msg or "（无回应）"
            result = await execute_all(
                db,
                agent,
                reply,
                user_id=user.id,
                user_intent=message,
                execution_context=ExecutionContext(
                    user_id=user.id,
                    user_intent=message,
                    agent_runner=runtime.agent_runner,
                ),
            )
            reply = fold_notes(reply, result)
            ai_message = await desktop_chat_repository.save_message(
                db,
                owner_user_id=user.id,
                speaker_type=SPEAKER_AI,
                speaker_agent_id=agent.id,
                speaker_name=agent.name,
                content=reply,
            )
            conversation.append((agent.name, reply))
            yield ("message_end", desktop_chat_repository.message_dict(ai_message))

            for consulted, consult_record in result.consult_replies:
                answer = consult_record.output_content or consult_record.error_msg or "（无回应）"
                yield (
                    "message_start",
                    {
                        "speaker_agent_id": str(consulted.id),
                        "speaker_name": consulted.name,
                    },
                )
                yield ("delta", {"text": answer})
                consulted_message = await desktop_chat_repository.save_message(
                    db,
                    owner_user_id=user.id,
                    speaker_type=SPEAKER_AI,
                    speaker_agent_id=consulted.id,
                    speaker_name=consulted.name,
                    content=answer,
                )
                conversation.append((consulted.name, answer))
                yield (
                    "message_end",
                    desktop_chat_repository.message_dict(consulted_message),
                )


async def try_orchestrate(
    db: AsyncSession, user: SysUser, assistant: AgentRole, message: str
) -> dict[str, Any] | None:
    from app.services import orchestration_service

    try:
        return await orchestration_service.start(
            db,
            message,
            creator_id=user.id,
            assignee_agent_id=assistant.id,
            operator_id=user.id,
        )
    except Exception:  # noqa: BLE001 - orchestration failure falls back to chat
        logger.warning("桌面编排启动失败，退回普通对话", exc_info=True)
        return None


def progress_text(snapshot: dict[str, Any]) -> str:
    icon = {
        "accepted": "✅",
        "succeeded": "✅",
        "reported": "⏸",
        "waiting_human": "⏸",
        "executing": "▶",
        "running": "▶",
        "created": "○",
        "dispatched": "○",
        "queued": "○",
        "rejected": "✕",
        "failed": "✕",
        "cancelled": "✕",
    }
    lines = [
        f"【任务进度】已规划 {snapshot['total']} 步，完成 "
        f"{snapshot['accepted']}/{snapshot['total']}"
    ]
    for step in snapshot["steps"]:
        marker = icon.get(step["status"], "○")
        red_line = (
            "（红线·待您验收）"
            if step["red_line"] and step["status"] in ("reported", "waiting_human")
            else ""
        )
        lines.append(
            f"{marker} 步骤{step['step_no'] + 1}：{step['title']} "
            f"[{step['skill']}]{red_line}"
        )
    if snapshot["awaiting_human"]:
        lines.append("\n有红线步骤已执行完，等待您在任务卡中验收后继续。")
    elif snapshot["done"]:
        lines.append("\n全部步骤已完成。")
    return "\n".join(lines)


async def emit_orchestration(
    db: AsyncSession,
    user: SysUser,
    assistant: AgentRole,
    snapshot: dict[str, Any],
) -> AsyncIterator[Event]:
    yield ("orchestration", snapshot)
    message = await desktop_chat_repository.save_message(
        db,
        owner_user_id=user.id,
        speaker_type=SPEAKER_AI,
        speaker_agent_id=assistant.id,
        speaker_name=assistant.name,
        content=progress_text(snapshot),
    )
    yield ("message_end", desktop_chat_repository.message_dict(message))
