"""Pure conversation entities and roundtable policies."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

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
class ReplyPreview:
    id: uuid.UUID
    speaker_name: str
    content: str


@dataclass(frozen=True, slots=True)
class ConversationMessage:
    id: uuid.UUID
    owner_user_id: uuid.UUID
    speaker_type: str
    speaker_name: str
    content: str
    create_time: datetime
    speaker_agent_id: uuid.UUID | None = None
    reply_to_message_id: uuid.UUID | None = None
    reply_preview: ReplyPreview | None = None
    attachments: tuple[dict[str, Any], ...] = ()
    is_pinned: bool = False
    pinned_at: datetime | None = None
    pinned_by_user_id: uuid.UUID | None = None


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


_IMAGE_ATTACHMENT_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def describe_user_turn(content: str, attachments: tuple[dict[str, Any], ...]) -> str:
    """把用户这一轮的正文与附件合成模型可读文本。

    当前模型无视觉能力，纯图片消息正文只是「[附件]」占位符，若直接进对话记录，
    模型会因为"最后一条没有实质内容"而顺着上一条乱答。这里显式告诉模型收到了
    图片/文件、无法查看图片内容，让它据此回应而不是续答旧话题。
    """
    if not attachments:
        return content
    images = [a for a in attachments if _is_image_attachment(a)]
    files = [a for a in attachments if not _is_image_attachment(a)]
    notes: list[str] = []
    if images:
        names = "、".join(str(a.get("name", "")) for a in images)
        notes.append(f"发来{len(images)}张图片（{names}），你暂时无法查看图片内容")
    if files:
        names = "、".join(str(a.get("name", "")) for a in files)
        notes.append(f"发来{len(files)}个文件（{names}）")
    note = "；".join(notes)
    body = content.strip()
    # 纯附件时正文是占位符，去掉以免干扰
    if body in ("", "[附件]"):
        return f"（{note}）"
    return f"{body}\n（{note}）"


def _is_image_attachment(attachment: dict[str, Any]) -> bool:
    if str(attachment.get("type", "")).lower() == "image":
        return True
    name = str(attachment.get("name", "")).lower()
    return name.endswith(_IMAGE_ATTACHMENT_EXTENSIONS)


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


def direct_chat_prompt(
    participant: Participant,
    conversation: tuple[tuple[str, str], ...],
) -> str:
    return (
        f"以下是你与同事的最近对话记录：\n{transcript(conversation)}\n\n"
        f"请以「{participant.name}」的身份，直接回复同事最后一条消息。"
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
