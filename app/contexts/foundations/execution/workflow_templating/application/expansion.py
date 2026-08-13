"""模板展开：把 TemplateStep 的 expert_code 解析成 assignee_expert_id（纯逻辑，不读 DB）。

roster 解析由调用方注入（resolve: code→uuid|None），故本模块可纯单测。未知/缺失 code → None，
复用 P3-2 运行时优雅降级（回落 run 的单一 assignee，不因坏 code 拒整份模板）。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from app.contexts.foundations.execution.workflow_templating.contracts import (
    ResolvedStep,
    WorkflowTemplateView,
)


def expand_template(
    view: WorkflowTemplateView,
    resolve: Callable[[str], uuid.UUID | None],
) -> list[ResolvedStep]:
    """把模板每步的 expert_code 经 resolve 解析成 assignee_expert_id，保序、透传依赖。"""
    return [
        ResolvedStep(
            no=step.no,
            title=step.title,
            skill=step.skill,
            instruction=step.instruction,
            depends_on=step.depends_on,
            assignee_expert_id=resolve(step.expert_code) if step.expert_code else None,
        )
        for step in view.steps
    ]
