"""Framework-independent Group Messaging entities and invariants."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.contexts.shared_kernel import InvalidInput, RuleViolation

MEMBER_HUMAN = "human"
MEMBER_AI = "ai"
SPEAKER_HUMAN = "human"
SPEAKER_AI = "ai"
MAX_FANOUT = 3
PROMOTE_TARGETS = ("proposal", "task")


@dataclass(frozen=True, slots=True)
class MemberDraft:
    member_type: str
    member_id: uuid.UUID
    member_name: str = ""

    @classmethod
    def from_mapping(cls, value: dict[str, Any]) -> MemberDraft | None:
        member_type = value.get("member_type")
        member_id = value.get("member_id")
        if member_type not in (MEMBER_HUMAN, MEMBER_AI) or not member_id:
            return None
        parsed_id = member_id if isinstance(member_id, uuid.UUID) else uuid.UUID(str(member_id))
        return cls(
            member_type=member_type,
            member_id=parsed_id,
            member_name=str(value.get("member_name") or ""),
        )


@dataclass(slots=True)
class Channel:
    id: uuid.UUID
    name: str
    create_time: datetime
    department_id: uuid.UUID | None = None
    default_agent_id: uuid.UUID | None = None
    creator_id: uuid.UUID | None = None
    is_archived: bool = False
    is_deleted: bool = False

    def is_owner(self, user_id: uuid.UUID) -> bool:
        return self.creator_id is not None and self.creator_id == user_id

    def ensure_postable(self) -> None:
        if self.is_archived:
            raise RuleViolation("频道已归档，不可发言")

    def ensure_owner_is_not_removed(self, *, member_type: str, member_id: uuid.UUID) -> None:
        if member_type == MEMBER_HUMAN and self.is_owner(member_id):
            raise InvalidInput("不能踢出群主")

    def archive(self) -> None:
        self.is_archived = True

    def disband(self) -> None:
        self.is_deleted = True


@dataclass(slots=True)
class Message:
    id: uuid.UUID
    channel_id: uuid.UUID
    speaker_type: str
    speaker_id: uuid.UUID | None
    speaker_name: str
    content: str
    create_time: datetime
    mentioned_agent_ids: tuple[str, ...] = ()
    ai_source_record_id: uuid.UUID | None = None
    ref_type: str | None = None
    ref_id: uuid.UUID | None = None
    attachments: tuple[dict[str, Any], ...] = ()
    is_deleted: bool = False

    def assert_promotable(self, target: str) -> None:
        if target not in PROMOTE_TARGETS:
            raise RuleViolation(f"target 仅支持 {'/'.join(PROMOTE_TARGETS)}")
        if self.ref_id is not None:
            raise RuleViolation("该消息已升格过")

    def record_promotion(self, *, target: str, ref_id: uuid.UUID) -> None:
        self.assert_promotable(target)
        self.ref_type = target
        self.ref_id = ref_id


def deduplicate_mentions(agent_ids: tuple[uuid.UUID, ...]) -> tuple[uuid.UUID, ...]:
    """Preserve mention order while enforcing the current fan-out guardrail."""
    seen: list[uuid.UUID] = []
    for agent_id in agent_ids:
        if agent_id not in seen:
            seen.append(agent_id)
        if len(seen) == MAX_FANOUT:
            break
    return tuple(seen)
