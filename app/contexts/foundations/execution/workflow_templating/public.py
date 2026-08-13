"""workflow_templating Context 对外选择器 + 组合根。

发起路径（P4）：repo 取模板视图 → roster 批解析 expert_code → 纯 expander 展开成 ResolvedStep。
管理路径（P5）：注入 capability 白名单跑纯校验 → 单写者 repo → commit → 返回 admin view。
DB 编排落在本 Context 根（允许触 repo + AsyncSession）；application/ 保持纯（校验/展开无 DB）。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.capability_catalog.public import list_capabilities
from app.contexts.foundations.execution.workflow_templating.application.expansion import (
    expand_template,
)
from app.contexts.foundations.execution.workflow_templating.application.validation import (
    validate_template_steps,
)
from app.contexts.foundations.execution.workflow_templating.contracts import (
    CreateTemplateCommand,
    ResolvedStep,
    TemplateAdminView,
    TemplateStep,
    UpdateTemplateCommand,
    WorkflowTemplateView,
)
from app.contexts.foundations.execution.workflow_templating.infrastructure import (
    repository,
    roster,
)
from app.contexts.foundations.organization_structure.public import get_node
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation

list_enabled = repository.list_enabled


async def load_template_steps(
    session: AsyncSession, template_id: uuid.UUID
) -> list[ResolvedStep] | None:
    """载模板并确定性展开成 ResolvedStep；模板不存在/停用 → None（bootstrap 回落 LLM 路径）。"""
    view = await repository.get(session, template_id)
    if view is None:
        return None
    codes = {step.expert_code for step in view.steps if step.expert_code}
    roster_map = await roster.load_agent_ids(session, codes)
    return expand_template(view, roster_map.get)


# ── 管理面（P5-1）：校验 → 单写者 repo → commit ──────────────────
async def _valid_skills() -> frozenset[str]:
    """已注册能力 key 集（拦未注册 skill，否则运行期被 tool_dispatcher 判 REJECTED）。"""
    return frozenset(d.key for d in await list_capabilities())


async def _require_department(session: AsyncSession, department_id: uuid.UUID | None) -> None:
    """给了归属部门则先验存在，否则坏 FK 会在 commit 抛 IntegrityError（500）。不存在 → 404。"""
    if department_id is not None:
        await get_node(session, department_id)  # 不存在即 raise ResourceNotFound


async def list_templates(
    session: AsyncSession, department_id: uuid.UUID | None = None
) -> list[TemplateAdminView]:
    """列出未软删模板（含停用）；给 department_id 则按归属过滤。"""
    return await repository.list_all(session, department_id)


async def get_template(session: AsyncSession, template_id: uuid.UUID) -> TemplateAdminView:
    """取一张模板全字段；不存在 → ResourceNotFound。"""
    view = await repository.get_any(session, template_id)
    if view is None:
        raise ResourceNotFound("工作流模板不存在")
    return view


async def create_template(
    session: AsyncSession, cmd: CreateTemplateCommand
) -> TemplateAdminView:
    """校验步骤后建模板。"""
    validate_template_steps(cmd.steps, await _valid_skills())
    await _require_department(session, cmd.department_id)
    new_id = await repository.create(session, cmd)
    await session.commit()
    return await get_template(session, new_id)


async def update_template(
    session: AsyncSession, template_id: uuid.UUID, cmd: UpdateTemplateCommand
) -> TemplateAdminView:
    """改模板；不存在 → ResourceNotFound。给了 steps 才重新校验。"""
    if await repository.get_any(session, template_id) is None:
        raise ResourceNotFound("工作流模板不存在")
    if cmd.steps is not None:
        validate_template_steps(cmd.steps, await _valid_skills())
    await _require_department(session, cmd.department_id)
    await repository.update(session, template_id, cmd)
    await session.commit()
    return await get_template(session, template_id)


async def delete_template(session: AsyncSession, template_id: uuid.UUID) -> None:
    """软删模板；不存在 → ResourceNotFound；种子模板拒删 → RuleViolation。"""
    view = await repository.get_any(session, template_id)
    if view is None:
        raise ResourceNotFound("工作流模板不存在")
    if view.is_seed:
        raise RuleViolation("种子模板不可删除，可停用")
    await repository.soft_delete(session, template_id)
    await session.commit()


__all__ = [
    "CreateTemplateCommand",
    "ResolvedStep",
    "TemplateAdminView",
    "TemplateStep",
    "UpdateTemplateCommand",
    "WorkflowTemplateView",
    "create_template",
    "delete_template",
    "get_template",
    "list_enabled",
    "list_templates",
    "load_template_steps",
    "update_template",
]
