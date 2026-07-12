"""任务卡请求/响应模型。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SubTask(BaseModel):
    """拆解子任务项。"""

    title: str = Field(min_length=1, max_length=200)
    task_type: str | None = Field(default=None, max_length=32)
    priority: str | None = Field(default=None, max_length=16)
    assignee_agent_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class TaskCreate(BaseModel):
    """创建任务卡。"""

    title: str = Field(min_length=1, max_length=200)
    task_type: str = Field(min_length=1, max_length=32)
    priority: str = Field(default="normal", max_length=16)
    assignee_agent_id: uuid.UUID | None = None
    parent_id: uuid.UUID | None = None
    sla_hours: int | None = Field(default=None, ge=1)
    payload: dict[str, Any] = Field(default_factory=dict)


class DecomposeRequest(BaseModel):
    """拆解任务为子任务。"""

    subtasks: list[SubTask] = Field(min_length=1)


class TransitionRequest(BaseModel):
    """状态流转。"""

    to_status: str = Field(min_length=1, max_length=24)
    note: str | None = Field(default=None, max_length=500)
    result_content: str | None = None


class TaskOut(BaseModel):
    """任务卡。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    task_type: str
    priority: str
    status: str
    creator_id: uuid.UUID
    assignee_agent_id: uuid.UUID | None
    parent_id: uuid.UUID | None
    sla_hours: int | None
    result_content: str | None
    create_time: datetime


class TaskLogOut(BaseModel):
    """流转日志。"""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    from_status: str | None
    to_status: str
    operator_id: uuid.UUID | None
    note: str | None
    create_time: datetime
