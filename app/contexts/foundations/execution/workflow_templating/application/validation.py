"""模板步骤纯校验（docs/25 P5-1）——无 DB、可纯单测。

拦下会在运行期才炸的坏模板：未注册 skill（会被 tool_dispatcher 判 REJECTED）、悬挂/自依赖、
依赖成环（会让 durable workflow 永远等不到前置）。expert_code 不强校验——未知 code 运行期
roster 优雅回落 None（与 P4 展开一致）。校验权威在后端；前端 validateSteps 只作即时 UX。
"""

from __future__ import annotations

from collections.abc import Sequence

from app.contexts.foundations.execution.workflow_templating.contracts import TemplateStep
from app.contexts.shared_kernel import InvalidInput


def validate_template_steps(
    steps: Sequence[TemplateStep], valid_skills: frozenset[str]
) -> None:
    """校验模板步骤，违规 raise InvalidInput（映射 400）；全通过返回 None。"""
    if not steps:
        raise InvalidInput("模板至少需要一个步骤")

    seen: set[int] = set()
    for step in steps:
        if step.no < 0:
            raise InvalidInput(f"步骤序号不能为负：{step.no}")
        if step.no in seen:
            raise InvalidInput(f"步骤序号重复：{step.no}")
        seen.add(step.no)
        if not step.title.strip():
            raise InvalidInput(f"步骤 {step.no} 缺少标题")
        if not step.instruction.strip():
            raise InvalidInput(f"步骤 {step.no} 缺少指令")
        if step.skill not in valid_skills:
            raise InvalidInput(f"步骤 {step.no} 使用了未注册能力：{step.skill}")

    for step in steps:
        for dep in step.depends_on:
            if dep == step.no:
                raise InvalidInput(f"步骤 {step.no} 不能依赖自身")
            if dep not in seen:
                raise InvalidInput(f"步骤 {step.no} 依赖了不存在的步骤：{dep}")

    _reject_cycle(steps)


def _reject_cycle(steps: Sequence[TemplateStep]) -> None:
    """Kahn 拓扑排序：无法排完（剩下的构成环）即 raise。"""
    indegree = {step.no: len(step.depends_on) for step in steps}
    dependents: dict[int, list[int]] = {step.no: [] for step in steps}
    for step in steps:
        for dep in step.depends_on:
            dependents[dep].append(step.no)

    queue = [no for no, deg in indegree.items() if deg == 0]
    resolved = 0
    while queue:
        no = queue.pop()
        resolved += 1
        for nxt in dependents[no]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                queue.append(nxt)

    if resolved != len(steps):
        raise InvalidInput("步骤依赖存在环，无法编排")
