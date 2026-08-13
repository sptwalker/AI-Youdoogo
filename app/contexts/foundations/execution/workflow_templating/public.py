"""workflow_templating Context 对外选择器（bootstrap 经此载模板+展开，不直连 infrastructure）。

组合根装配点：repo 取模板视图 → roster 批解析 expert_code → 纯 expander 展开成 ResolvedStep。
bootstrap 把 ResolvedStep 转 WorkflowPlanStep 喂 start（foundations 不反依赖 facade）。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.workflow_templating.application.expansion import (
    expand_template,
)
from app.contexts.foundations.execution.workflow_templating.contracts import (
    ResolvedStep,
    TemplateStep,
    WorkflowTemplateView,
)
from app.contexts.foundations.execution.workflow_templating.infrastructure import (
    repository,
    roster,
)

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


__all__ = [
    "ResolvedStep",
    "TemplateStep",
    "WorkflowTemplateView",
    "list_enabled",
    "load_template_steps",
]
