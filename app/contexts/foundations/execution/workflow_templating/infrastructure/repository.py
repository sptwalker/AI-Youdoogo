"""workflow_template 表的**唯一**持久化写者（架构门禁：一模型一写者 Context）。

读职责：按 id 取一张启用模板快照、列出启用中的模板（供发起展开）。
写职责（P5 管理面）：get_any/list_all（含停用，供管理）+ create/update/soft_delete。
种子模板经迁移写入首张；此后增删改均经本文件。steps JSON 解析成不可变 TemplateStep
（缺字段安全回落：depends_on 空、expert_code None）。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_templating.contracts import (
    CreateTemplateCommand,
    TemplateAdminView,
    TemplateStep,
    UpdateTemplateCommand,
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


def _step_to_dict(step: TemplateStep) -> dict[str, Any]:
    return {
        "no": step.no,
        "title": step.title,
        "skill": step.skill,
        "instruction": step.instruction,
        "depends_on": list(step.depends_on),
        "expert_code": step.expert_code,
    }


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


# ── 管理面（P5-1）：含停用、全字段 ──────────────────────────────
def _to_admin_view(row: WorkflowTemplate) -> TemplateAdminView:
    return TemplateAdminView(
        id=row.id,
        name=row.name,
        description=row.description,
        department_id=row.department_id,
        steps=tuple(_to_step(step) for step in row.steps),
        enabled=row.enabled,
        is_seed=row.is_seed,
    )


async def get_any(session: AsyncSession, template_id: uuid.UUID) -> TemplateAdminView | None:
    """按 id 取一张模板全字段（含停用）；不存在/已软删 → None。"""
    row = await session.get(WorkflowTemplate, template_id)
    if row is None or row.is_delete:
        return None
    return _to_admin_view(row)


async def list_all(
    session: AsyncSession, department_id: uuid.UUID | None = None
) -> list[TemplateAdminView]:
    """列出未软删的模板（含停用）；给 department_id 则按归属部门过滤。"""
    stmt = select(WorkflowTemplate).where(WorkflowTemplate.is_delete.is_(False))
    if department_id is not None:
        stmt = stmt.where(WorkflowTemplate.department_id == department_id)
    rows = (await session.execute(stmt)).scalars()
    return [_to_admin_view(row) for row in rows]


async def create(session: AsyncSession, cmd: CreateTemplateCommand) -> uuid.UUID:
    """建一张模板，返回新 id（调用方负责 commit）。"""
    row = WorkflowTemplate(
        name=cmd.name,
        description=cmd.description,
        department_id=cmd.department_id,
        steps=[_step_to_dict(step) for step in cmd.steps],
        enabled=True,
        is_seed=False,
    )
    session.add(row)
    await session.flush()
    return row.id


async def update(
    session: AsyncSession, template_id: uuid.UUID, cmd: UpdateTemplateCommand
) -> None:
    """PATCH 更新：只写非 None 字段（调用方已确认存在、负责 commit）。

    # ponytail: department_id/description=None 一律视为「不改」（保 enabled-only PATCH 安全），
    #   故无法经 PATCH 置空；需清空归属/描述时重建模板。
    """
    row = await session.get(WorkflowTemplate, template_id)
    if row is None:
        return
    if cmd.name is not None:
        row.name = cmd.name
    if cmd.description is not None:
        row.description = cmd.description
    if cmd.department_id is not None:
        row.department_id = cmd.department_id
    if cmd.steps is not None:
        row.steps = [_step_to_dict(step) for step in cmd.steps]
    if cmd.enabled is not None:
        row.enabled = cmd.enabled


async def soft_delete(session: AsyncSession, template_id: uuid.UUID) -> None:
    """软删（置 is_delete=True；调用方已确认非种子、负责 commit）。"""
    row = await session.get(WorkflowTemplate, template_id)
    if row is not None:
        row.is_delete = True
