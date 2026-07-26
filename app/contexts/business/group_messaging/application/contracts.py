"""Plain Group Messaging commands, queries, results, and stream values."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

DISBAND_ARCHIVE_EVENT = "discussion.channel.archive"
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
ARCHIVE_FILE_NAMESPACE = uuid.UUID("1e08b822-57c4-45ab-86f9-b0f494d5aba6")


@dataclass(frozen=True, slots=True)
class Principal:
    id: uuid.UUID
    role_code: str = "member"

    @property
    def is_manager(self) -> bool:
        return self.role_code in {"admin", "executive"}


@dataclass(frozen=True, slots=True)
class MemberInput:
    member_type: str
    member_id: uuid.UUID
    member_name: str = ""


@dataclass(frozen=True, slots=True)
class CreateChannelCommand:
    name: str
    creator_id: uuid.UUID | None = None
    creator_name: str = ""
    department_id: uuid.UUID | None = None
    default_agent_id: uuid.UUID | None = None
    members: tuple[MemberInput, ...] = ()


@dataclass(frozen=True, slots=True)
class ChannelResult:
    id: uuid.UUID
    name: str
    department_id: uuid.UUID | None
    default_agent_id: uuid.UUID | None
    creator_id: uuid.UUID | None
    is_archived: bool
    create_time: datetime
    unread: int | None = None

    def as_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": str(self.id),
            "name": self.name,
            "department_id": str(self.department_id) if self.department_id else None,
            "default_agent_id": (str(self.default_agent_id) if self.default_agent_id else None),
            "creator_id": str(self.creator_id) if self.creator_id else None,
            "is_archived": self.is_archived,
            "create_time": self.create_time.isoformat(),
        }
        if self.unread is not None:
            value["unread"] = self.unread
        return value


@dataclass(frozen=True, slots=True)
class MemberResult:
    member_type: str
    member_id: uuid.UUID
    member_name: str

    def as_dict(self) -> dict[str, str]:
        return {
            "member_type": self.member_type,
            "member_id": str(self.member_id),
            "member_name": self.member_name,
        }


@dataclass(frozen=True, slots=True)
class MessageResult:
    id: uuid.UUID
    channel_id: uuid.UUID
    speaker_type: str
    speaker_id: uuid.UUID | None
    speaker_name: str
    content: str
    mentioned_agent_ids: tuple[str, ...]
    ai_source_record_id: uuid.UUID | None
    ref_type: str | None
    ref_id: uuid.UUID | None
    attachments: tuple[dict[str, Any], ...]
    create_time: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "channel_id": str(self.channel_id),
            "speaker_type": self.speaker_type,
            "speaker_id": str(self.speaker_id) if self.speaker_id else None,
            "speaker_name": self.speaker_name,
            "content": self.content,
            "mentioned_agent_ids": list(self.mentioned_agent_ids),
            "ai_source_record_id": (
                str(self.ai_source_record_id) if self.ai_source_record_id else None
            ),
            "ref_type": self.ref_type,
            "ref_id": str(self.ref_id) if self.ref_id else None,
            "attachments": [dict(value) for value in self.attachments],
            "create_time": self.create_time.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PostMessageCommand:
    channel_id: uuid.UUID
    speaker_id: uuid.UUID | None
    speaker_name: str
    content: str
    mentioned_agent_ids: tuple[uuid.UUID, ...] = ()
    attachments: tuple[dict[str, Any], ...] = ()
    require_member_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AgentReplyRequest:
    agent_id: uuid.UUID
    user_id: uuid.UUID | None
    channel_name: str
    content: str
    recent_context: str


@dataclass(frozen=True, slots=True)
class AgentReplyStreamEvent:
    name: str
    speaker_agent_id: uuid.UUID | None = None
    speaker_name: str = ""
    text: str = ""
    content: str = ""
    source_record_id: uuid.UUID | None = None
    publish_realtime: bool = True


@dataclass(frozen=True, slots=True)
class MessageStreamEvent:
    name: str
    data: dict[str, Any]

    @classmethod
    def message_persisted(cls, message: MessageResult) -> MessageStreamEvent:
        return cls("message_end", message.as_dict())

    @classmethod
    def turn_started(
        cls,
        *,
        speaker_agent_id: uuid.UUID | None,
        speaker_name: str,
    ) -> MessageStreamEvent:
        return cls(
            "message_start",
            {
                "speaker_agent_id": str(speaker_agent_id) if speaker_agent_id else None,
                "speaker_name": speaker_name,
            },
        )

    @classmethod
    def delta(cls, text: str) -> MessageStreamEvent:
        return cls("delta", {"text": text})


@dataclass(frozen=True, slots=True)
class UploadAttachmentCommand:
    name: str
    content: bytes
    content_type: str


@dataclass(frozen=True, slots=True)
class AttachmentResult:
    attachment_type: str
    name: str
    storage_path: str
    size: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.attachment_type,
            "name": self.name,
            "storage_path": self.storage_path,
            "size": self.size,
        }


@dataclass(frozen=True, slots=True)
class AttachmentDownloadResult:
    name: str
    content: bytes


@dataclass(frozen=True, slots=True)
class ArchiveRequest:
    channel_id: uuid.UUID
    channel_name: str
    creator_id: uuid.UUID
    transcript: str
    file_id: uuid.UUID


@dataclass(frozen=True, slots=True)
class PromotionRequest:
    target: str
    title: str
    content: str
    creator_id: uuid.UUID
    source_message_id: uuid.UUID


def archive_file_id(channel_id: uuid.UUID) -> uuid.UUID:
    return uuid.uuid5(ARCHIVE_FILE_NAMESPACE, str(channel_id))
