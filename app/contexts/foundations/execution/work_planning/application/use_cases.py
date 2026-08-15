"""Planning policy that produces a validated plan without persistence access."""

from __future__ import annotations

import json
import re
import uuid

from app.contexts.foundations.execution.work_planning.application.ports import (
    PlanningModelPort,
)
from app.contexts.foundations.execution.work_planning.contracts.planning import (
    PlanWorkRequest,
    PlanWorkResult,
    WorkflowPlan,
    WorkflowPlanStep,
)

MAX_PLAN_STEPS = 16
# 红线判定唯一事实源在 workflow_runtime/domain/policies.py（建步时盖 red_line 戳、运行时强制停点）；
# 规划器不再自留一份 AUTOMATIC 清单，避免两份分叉——前端预览高亮亦对齐 policies 的自动能力集。


def _parse_expert(value: object) -> uuid.UUID | None:
    """可选逐步承接专家（P3-2）：合法 UUID 字符串才采纳，缺省/非法一律回落 None。

    非法值不判整份计划失败——逐步派发只是覆盖项，缺省语义是「回落 run 单派发」，
    graceful degrade 比因一个可选字段拒整份多步计划更符合红线安全回落。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return uuid.UUID(value.strip())
    except ValueError:
        return None


def parse_workflow_plan(raw: str, request: PlanWorkRequest) -> PlanWorkResult:
    """Translate untrusted model JSON into the immutable published plan."""
    try:
        data = json.loads(_strip_fence(raw))
    except (json.JSONDecodeError, TypeError):
        return PlanWorkResult(None, "invalid_json")
    if not isinstance(data, dict) or not data.get("multi"):
        return PlanWorkResult(None, "single_action")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or len(raw_steps) < 2:
        return PlanWorkResult(None, "insufficient_steps")
    steps: list[WorkflowPlanStep] = []
    for item in raw_steps[:MAX_PLAN_STEPS]:
        if not isinstance(item, dict):
            return PlanWorkResult(None, "invalid_step")
        number = item.get("no")
        title = item.get("title")
        capability = item.get("skill") or "other"
        instruction = item.get("instruction") or title
        dependencies = item.get("depends_on") or []
        if (
            not isinstance(number, int)
            or not isinstance(title, str)
            or not isinstance(capability, str)
            or not isinstance(instruction, str)
            or not isinstance(dependencies, list)
            or not all(isinstance(dependency, int) for dependency in dependencies)
        ):
            return PlanWorkResult(None, "invalid_step")
        try:
            steps.append(
                WorkflowPlanStep(
                    number=number,
                    title=title.strip(),
                    capability_key=capability.strip(),
                    instruction=instruction.strip(),
                    depends_on=tuple(dependencies),
                    assignee_expert_id=_parse_expert(item.get("expert")),
                )
            )
        except ValueError:
            return PlanWorkResult(None, "invalid_step")
    try:
        return PlanWorkResult(WorkflowPlan(request.intent, tuple(steps)))
    except ValueError as exc:
        return PlanWorkResult(None, str(exc))


class PlanWorkApplication:
    """Ask for a proposal and validate it; never persists runtime or task state."""

    def __init__(self, model: PlanningModelPort) -> None:
        self._model = model

    async def execute(self, request: PlanWorkRequest) -> PlanWorkResult:
        raw = await self._model.propose(request.intent)
        return parse_workflow_plan(raw, request)


def _strip_fence(raw: str) -> str:
    text = raw.strip()
    match = re.search(r"\{.*\}", text, re.DOTALL)
    return match.group(0) if match else text
