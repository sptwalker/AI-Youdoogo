"""workflow_template 表的**唯一**持久化写者（架构门禁：一模型一写者 Context）。

只读职责：按 id 取一张模板快照、列出启用中的模板。种子模板经迁移写入，不在 repo 建。
steps JSON 解析成不可变 TemplateStep（缺字段安全回落：depends_on 空、expert_code None）。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_templating.contracts import (
    TemplateStep,
    WorkflowTemplateView,
)
from app.models.workflow_template import WorkflowTemplate


def _to_step(raw: dict[str, Any]) -> TemplateStep:
    return TemplateStep(
        no=int(raw["no"]),
        title=str(raw["title"]),
        skill=str(raw["skill"]),
        instruction=str(raw["instruction"]),
        depends_on=tuple(int(dep) for dep in raw.get("depends_on", ())),
        expert_code=raw.get("expert_code") or None,
    )


def _to_view(row: WorkflowTemplate) -> WorkflowTemplateView:
    return WorkflowTemplateView(
        id=row.id,
        name=row.name,
        steps=tuple(_to_step(step) for step in row.steps),
    )


async def get(session: AsyncSession, template_id: uuid.UUID) -> WorkflowTemplateView | None:
    """按 id 取一张启用中的模板快照；不存在/停用/已删 → None。"""
    row = await session.get(WorkflowTemplate, template_id)
    if row is None or row.is_delete or not row.enabled:
        return None
    return _to_view(row)


async def list_enabled(session: AsyncSession) -> list[WorkflowTemplateView]:
    """列出启用中的模板快照。"""
    rows = (
        await session.execute(
            select(WorkflowTemplate).where(
                WorkflowTemplate.enabled.is_(True),
                WorkflowTemplate.is_delete.is_(False),
            )
        )
    ).scalars()
    return [_to_view(row) for row in rows]
