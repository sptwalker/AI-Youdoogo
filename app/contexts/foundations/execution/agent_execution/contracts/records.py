"""Immutable Agent execution evidence views."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class AgentExecutionRecordView:
    id: uuid.UUID
    agent_role_id: uuid.UUID
    task_type: str
    input_summary: str | None
    output_content: str | None
    model_used: str | None
    status: str
    error_msg: str | None
    duration_ms: int | None
    create_time: datetime
