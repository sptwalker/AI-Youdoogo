"""Plain commands, results, and stream values for Assistant Conversations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

CONVERSATION_ARCHIVE_NAMESPACE = uuid.UUID("4179ee5b-aa21-45ed-a4a7-81790ca85ccd")


@dataclass(frozen=True, slots=True)
class Principal:
    id: uuid.UUID
    display_name: str
    department_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class AssistantResult:
    id: uuid.UUID
    owner_user_id: uuid.UUID
    name: str

    def as_dict(self) -> dict[str, str]:
        return {"id": str(self.id), "name": self.name}


@dataclass(frozen=True, slots=True)
class AgentResult:
    id: uuid.UUID
    name: str
    title: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"id": str(self.id), "name": self.name, "title": self.title}


@dataclass(frozen=True, slots=True)
class ReplyPreviewResult:
    id: uuid.UUID
    speaker_name: str
    content: str

    def as_dict(self) -> dict[str, str]:
        return {
            "id": str(self.id),
            "speaker_name": self.speaker_name,
            "content": self.content,
        }


@dataclass(frozen=True, slots=True)
class MessageResult:
    id: uuid.UUID
    speaker_type: str
    speaker_name: str
    content: str
    create_time: datetime
    speaker_agent_id: uuid.UUID | None = None
    reply_to_message_id: uuid.UUID | None = None
    reply_preview: ReplyPreviewResult | None = None
    attachments: tuple[dict[str, Any], ...] = ()
    is_pinned: bool = False
    pinned_at: datetime | None = None
    pinned_by_user_id: uuid.UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "speaker_type": self.speaker_type,
            "speaker_agent_id": (str(self.speaker_agent_id) if self.speaker_agent_id else None),
            "speaker_name": self.speaker_name,
            "content": self.content,
            "create_time": self.create_time.isoformat(),
            "reply_to_message_id": (
                str(self.reply_to_message_id) if self.reply_to_message_id else None
            ),
            "reply_preview": self.reply_preview.as_dict() if self.reply_preview else None,
            "attachments": [dict(value) for value in self.attachments],
            "is_pinned": self.is_pinned,
            "pinned_at": self.pinned_at.isoformat() if self.pinned_at else None,
            "pinned_by_user_id": (
                str(self.pinned_by_user_id) if self.pinned_by_user_id else None
            ),
        }


@dataclass(frozen=True, slots=True)
class ConversationResult:
    assistant: AssistantResult
    messages: tuple[MessageResult, ...]
    addable_agents: tuple[AgentResult, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "assistant": self.assistant.as_dict(),
            "messages": [message.as_dict() for message in self.messages],
            "addable_agents": [agent.as_dict() for agent in self.addable_agents],
        }


@dataclass(frozen=True, slots=True)
class SendMessageCommand:
    principal: Principal
    message: str
    add_agent_ids: tuple[uuid.UUID, ...] = ()
    reply_to_message_id: uuid.UUID | None = None
    attachments: tuple[dict[str, Any], ...] = ()
    default_rounds: int = 2
    max_add: int = 2
    max_rounds: int = 3
    recent_context: int = 20


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
class ArchiveConversationRequest:
    principal_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    document_id: uuid.UUID
    title_template: str
    transcript: str


def conversation_archive_document_id(
    principal_id: uuid.UUID,
    message_ids: tuple[uuid.UUID, ...],
) -> uuid.UUID:
    """Identify one exact archive batch so a failed delete can be replayed safely."""
    if not message_ids:
        raise ValueError("conversation archive requires at least one message")
    batch_key = ",".join(str(message_id) for message_id in sorted(message_ids, key=str))
    return uuid.uuid5(CONVERSATION_ARCHIVE_NAMESPACE, f"{principal_id}:{batch_key}")


@dataclass(frozen=True, slots=True)
class AgentExecutionRequest:
    participant_id: uuid.UUID
    principal_id: uuid.UUID
    original_message: str
    prompt: str


@dataclass(frozen=True, slots=True)
class ConsultedReply:
    participant_id: uuid.UUID
    participant_name: str
    content: str


@dataclass(frozen=True, slots=True)
class AgentExecutionEvent:
    name: str
    text: str = ""
    content: str = ""
    consultations: tuple[ConsultedReply, ...] = ()


@dataclass(frozen=True, slots=True)
class OrchestrationResult:
    payload: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class ConversationStreamEvent:
    name: str
    data: dict[str, Any]

    @classmethod
    def message_persisted(cls, message: MessageResult) -> ConversationStreamEvent:
        return cls("message_end", message.as_dict())

    @classmethod
    def turn_started(
        cls,
        *,
        speaker_agent_id: uuid.UUID,
        speaker_name: str,
    ) -> ConversationStreamEvent:
        return cls(
            "message_start",
            {
                "speaker_agent_id": str(speaker_agent_id),
                "speaker_name": speaker_name,
            },
        )

    @classmethod
    def delta(cls, text: str) -> ConversationStreamEvent:
        return cls("delta", {"text": text})

    @classmethod
    def orchestration_snapshot(
        cls, payload: Mapping[str, object]
    ) -> ConversationStreamEvent:
        return cls("orchestration", dict(payload))
