"""Plain request and response values for one expert consultation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ConsultHistoryTurn:
    role: str
    content: str


@dataclass(frozen=True, slots=True)
class ConsultExpertCommand:
    expert_id: uuid.UUID
    message: str
    history: tuple[ConsultHistoryTurn, ...] = ()
    user_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ConsultExpertResult:
    reply: str
    status: str
    execution_id: uuid.UUID | None = None
