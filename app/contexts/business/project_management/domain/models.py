"""Project Management 领域模型：项目聚合与生命周期（active/archived）。

纯领域对象，不依赖 ORM/框架。归档是软生命周期标记（docs/27 §5.2 裁决），非删除；归档后不可编辑。
项目是个人工作台的任务分组容器（docs/27 §5.3 裁决 #1：与任务卡区分开的独立聚合）。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.contexts.shared_kernel import RuleViolation

ACTIVE = "active"
ARCHIVED = "archived"


@dataclass(slots=True)
class Project:
    """项目聚合根。归档后 status=ARCHIVED 且不可再编辑。"""

    id: uuid.UUID
    name: str
    owner_id: uuid.UUID
    description: str | None
    status: str
    department_id: uuid.UUID | None
    archived_at: datetime | None
    create_time: datetime | None = None

    @classmethod
    def create(
        cls,
        *,
        project_id: uuid.UUID,
        owner_id: uuid.UUID,
        name: str,
        description: str | None,
        department_id: uuid.UUID | None,
        created_at: datetime,
    ) -> Project:
        return cls(
            id=project_id,
            name=_clean_name(name),
            owner_id=owner_id,
            description=description,
            status=ACTIVE,
            department_id=department_id,
            archived_at=None,
            create_time=created_at,
        )

    def rename(self, name: str) -> None:
        self._assert_editable()
        self.name = _clean_name(name)

    def set_description(self, description: str | None) -> None:
        self._assert_editable()
        self.description = description

    def archive(self, *, at: datetime) -> None:
        if self.status == ARCHIVED:
            raise RuleViolation("项目已归档")
        self.status = ARCHIVED
        self.archived_at = at

    def _assert_editable(self) -> None:
        if self.status == ARCHIVED:
            raise RuleViolation("项目已归档，不可编辑")


def _clean_name(name: str) -> str:
    cleaned = name.strip()
    if not cleaned:
        raise RuleViolation("项目名称不能为空")
    return cleaned
