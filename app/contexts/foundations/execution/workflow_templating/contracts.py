"""workflow_templating 契约：模板的传输无关只读视图 + 展开后步骤。

TemplateStep 为模板原始步（expert_code 引用部门承接人 agent_role.code）；ResolvedStep 为
expert_code 已解析成 assignee_expert_id 的展开步，bootstrap 转 WorkflowPlanStep 喂 start。
快照成不可变 dataclass，避免 commit 后 ORM expire-on-commit 懒加载。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class TemplateStep:
    """模板中一步的原始定义（expert_code = 部门承接人的 agent_role.code，可选）。"""

    no: int
    title: str
    skill: str
    instruction: str
    depends_on: tuple[int, ...] = ()
    expert_code: str | None = None


@dataclass(frozen=True)
class WorkflowTemplateView:
    """一张模板的只读快照（脱离 Session，读字段不再触库）。"""

    id: uuid.UUID
    name: str
    steps: tuple[TemplateStep, ...]


@dataclass(frozen=True)
class ResolvedStep:
    """expert_code 已解析为 assignee_expert_id 的展开步（未知 code → None 回落 run assignee）。"""

    no: int
    title: str
    skill: str
    instruction: str
    depends_on: tuple[int, ...]
    assignee_expert_id: uuid.UUID | None


@dataclass(frozen=True)
class TemplateAdminView:
    """管理面全字段快照（含停用/归属/种子标记），供 CRUD 列表与详情。"""

    id: uuid.UUID
    name: str
    description: str | None
    department_id: uuid.UUID | None
    steps: tuple[TemplateStep, ...]
    enabled: bool
    is_seed: bool


@dataclass(frozen=True)
class CreateTemplateCommand:
    """新建模板（steps 已校验后落库）。"""

    name: str
    description: str | None
    department_id: uuid.UUID | None
    steps: tuple[TemplateStep, ...]


@dataclass(frozen=True)
class UpdateTemplateCommand:
    """改模板（PATCH 语义：None 表示该字段不改）。"""

    name: str | None = None
    description: str | None = None
    department_id: uuid.UUID | None = None
    steps: tuple[TemplateStep, ...] | None = None
    enabled: bool | None = None
