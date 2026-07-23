"""Plain commands, results, and stream values for Assistant Conversations."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any


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
class MessageResult:
    id: uuid.UUID
    speaker_type: str
    speaker_name: str
    content: str
    create_time: datetime
    speaker_agent_id: uuid.UUID | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "speaker_type": self.speaker_type,
            "speaker_agent_id": (str(self.speaker_agent_id) if self.speaker_agent_id else None),
            "speaker_name": self.speaker_name,
            "content": self.content,
            "create_time": self.create_time.isoformat(),
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
    default_rounds: int = 2
    max_add: int = 2
    max_rounds: int = 3
    recent_context: int = 20


@dataclass(frozen=True, slots=True)
class ArchiveConversationRequest:
    principal_id: uuid.UUID
    knowledge_base_id: uuid.UUID
    title_template: str
    transcript: str


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
