"""组织架构请求/响应模型（F1）。"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NodeCreate(BaseModel):
    """新建部门（挂在 parent 下）。"""

    name: str = Field(min_length=1, max_length=64)
    parent_id: uuid.UUID
    code: str | None = Field(default=None, max_length=32)


class NodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    sort_order: int | None = None


class SupervisorSet(BaseModel):
    supervisor_user_id: uuid.UUID | None = None


class NodeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    code: str
    node_type: str
    level: int
    parent_id: uuid.UUID | None
    supervisor_user_id: uuid.UUID | None
    sort_order: int
    create_time: datetime


class EmployeeCreate(BaseModel):
    """在部门下新增智能体员工。"""

    name: str = Field(min_length=1, max_length=64)
    prompt_template: str = Field(min_length=1)
    title: str = Field(default="", max_length=64)
    tier: str = Field(default="member")
    model_role: str = Field(default="daily")
    duty: str | None = Field(default=None, max_length=500)
    report_to_id: uuid.UUID | None = None


class EmployeeUpdate(BaseModel):
    name: str | None = None
    prompt_template: str | None = None
    title: str | None = None
    tier: str | None = None
    model_role: str | None = None
    duty: str | None = Field(default=None, max_length=500)
    report_to_id: uuid.UUID | None = None
    department_id: uuid.UUID | None = None
    is_active: bool | None = None


class EmployeeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str | None
    name: str
    title: str
    tier: str
    department_id: uuid.UUID | None
    report_to_id: uuid.UUID | None
    model_role: str
    duty: str | None
    prompt_template: str
    is_seed: bool
    is_active: bool
    permission_scope: dict[str, Any]
    tools: list[Any]
    create_time: datetime
