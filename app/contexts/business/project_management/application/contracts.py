"""Project Management 应用层命令、查询与结果（与传输无关的纯数据）。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CreateProjectCommand:
    owner_id: uuid.UUID
    name: str
    description: str | None = None
    department_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class UpdateProjectCommand:
    project_id: uuid.UUID
    owner_id: uuid.UUID
    # None = 该字段不改（A1 不支持把 description 清空为 NULL，YAGNI，需要时再加显式清空语义）。
    name: str | None = None
    description: str | None = None


@dataclass(frozen=True, slots=True)
class ListProjectsQuery:
    owner_id: uuid.UUID
    status: str | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class ProjectResult:
    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    description: str | None
    status: str
    department_id: uuid.UUID | None
    archived_at: datetime | None
    create_time: datetime
