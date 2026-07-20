"""持久化工作流进度与执行追踪响应模型。"""

import uuid
from typing import Any

from pydantic import BaseModel, Field


class WorkflowStepOut(BaseModel):
    """工作流步骤进度。"""

    id: uuid.UUID
    task_card_id: uuid.UUID | None = None
    step_no: int
    title: str
    skill: str
    status: str
    red_line: bool
    attempt: int
    last_error: str | None = None
    output_data: dict[str, Any] = Field(default_factory=dict)


class WorkflowProgressOut(BaseModel):
    """工作流持久化进度快照。"""

    workflow_id: uuid.UUID
    parent_task_id: uuid.UUID | None = None
    trace_id: uuid.UUID
    status: str
    total: int
    completed: int
    awaiting_human: list[uuid.UUID] = Field(default_factory=list)
    steps: list[WorkflowStepOut] = Field(default_factory=list)
