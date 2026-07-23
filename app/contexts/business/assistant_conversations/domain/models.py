"""Pure conversation entities and roundtable policies."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime

from app.contexts.shared_kernel import RuleViolation

SPEAKER_USER = "user"
SPEAKER_AI = "ai"


@dataclass(frozen=True, slots=True)
class Assistant:
    id: uuid.UUID
    owner_user_id: uuid.UUID
    name: str
    personal_knowledge_base_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class Participant:
    id: uuid.UUID
    name: str
    title: str = ""


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    id: uuid.UUID
    owner_user_id: uuid.UUID
    speaker_type: str
    speaker_name: str
    content: str
    create_time: datetime
    speaker_agent_id: uuid.UUID | None = None


def deduplicate_added_agents(
    agent_ids: tuple[uuid.UUID, ...],
    *,
    assistant_id: uuid.UUID,
    max_add: int,
) -> tuple[uuid.UUID, ...]:
    """Validate the request limit and keep first-seen, non-assistant IDs."""
    ensure_added_agent_limit(agent_ids, max_add=max_add)
    seen = {assistant_id}
    result: list[uuid.UUID] = []
    for agent_id in agent_ids:
        if agent_id in seen:
            continue
        seen.add(agent_id)
        result.append(agent_id)
    return tuple(result)


def ensure_added_agent_limit(agent_ids: tuple[uuid.UUID, ...], *, max_add: int) -> None:
    if len(set(agent_ids)) > max_add:
        raise RuleViolation(f"最多再加入 {max_add} 个 AI")


def round_count(
    configured: int,
    *,
    participant_count: int,
    maximum: int,
) -> int:
    if participant_count <= 1:
        return 1
    return max(1, min(configured, maximum))


def transcript(conversation: tuple[tuple[str, str], ...]) -> str:
    return "\n".join(f"{name}：{content}" for name, content in conversation)


def roundtable_prompt(
    participant: Participant,
    participants: tuple[Participant, ...],
    conversation: tuple[tuple[str, str], ...],
) -> str:
    others = "、".join(item.name for item in participants if item.id != participant.id)
    return (
        f"以下是圆桌对话记录：\n{transcript(conversation)}\n\n"
        f"请以「{participant.name}」的身份，结合以上讨论"
        + (f"（在座还有{others}）" if others else "")
        + "简明发表你的看法，不要重复他人已说过的内容。"
    )


def progress_text(snapshot: Mapping[str, object]) -> str:
    """Render the legacy workflow snapshot without changing its payload."""
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
    total = _integer(snapshot["total"])
    accepted = _integer(snapshot["accepted"])
    lines = [f"【任务进度】已规划 {total} 步，完成 {accepted}/{total}"]
    raw_steps = snapshot.get("steps", ())
    steps = raw_steps if isinstance(raw_steps, (list, tuple)) else ()
    for raw_step in steps:
        if not isinstance(raw_step, Mapping):
            continue
        status = str(raw_step.get("status", ""))
        red_line = (
            "（红线·待您验收）"
            if bool(raw_step.get("red_line")) and status in ("reported", "waiting_human")
            else ""
        )
        lines.append(
            f"{icon.get(status, '○')} 步骤{_integer(raw_step.get('step_no', 0)) + 1}："
            f"{raw_step.get('title', '')} [{raw_step.get('skill', '')}]{red_line}"
        )
    if bool(snapshot.get("awaiting_human")):
        lines.append("\n有红线步骤已执行完，等待您在任务卡中验收后继续。")
    elif bool(snapshot.get("done")):
        lines.append("\n全部步骤已完成。")
    return "\n".join(lines)


def _integer(value: object) -> int:
    return value if isinstance(value, int) else int(str(value))
