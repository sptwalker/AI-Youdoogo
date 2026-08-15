"""AI 任务中心：先出计划（NL→DAG）让真人确认，再执行。复用 work_planning + workflow_runtime。

不新建引擎：
- POST /ai-tasks/plan   仅跑 plan_work 出计划预览，不落库、不执行，供真人确认。
- POST /ai-tasks/execute 用真人已确认、客户端回传的步骤重建 WorkflowPlan（__post_init__ 复校无环/
  依赖合法，信任边界），再走既有 task_management.start_workflow。

红线：对外/业务/资金/人事步骤的停点由 workflow_runtime 的 is_red_line 逐步判定强制（停
waiting_human），本入口不绕过、不放宽；creator_id 一律取登录用户，禁止客户端冒充。
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.contexts.business.task_management import public as task_management
from app.contexts.foundations.execution.work_planning import public as work_planning
from app.contexts.foundations.execution.workflow_runtime import public as workflow_runtime
from app.contexts.shared_kernel import RuleViolation
from app.platform.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(prefix="/ai-tasks", tags=["ai-tasks"])

DB = Annotated[AsyncSession, Depends(get_db)]


class _PlanRequest(BaseModel):
    request: str = Field(min_length=8, max_length=4000)
    title: str | None = Field(default=None, max_length=200)


class _PlanStep(BaseModel):
    number: int = Field(ge=0)
    title: str = Field(min_length=1, max_length=200)
    capability_key: str = Field(min_length=1, max_length=100)
    instruction: str = Field(min_length=1, max_length=4000)
    depends_on: list[int] = Field(default_factory=list)


class _ExecuteRequest(BaseModel):
    request: str = Field(min_length=8, max_length=4000)
    title: str | None = Field(default=None, max_length=200)
    steps: list[_PlanStep] = Field(min_length=1, max_length=50)


def _step_dict(step: work_planning.WorkflowPlanStep) -> dict[str, object]:
    return {
        "number": step.number,
        "title": step.title,
        "capability_key": step.capability_key,
        "instruction": step.instruction,
        "depends_on": list(step.depends_on),
    }


@router.post("/plan")
async def plan_ai_task(body: _PlanRequest, db: DB, user: CurrentUser) -> dict:
    """NL → 计划预览（DAG 步骤）。只出计划不执行，供真人确认后再调 /execute。"""
    planned = await work_planning.plan_work(
        work_planning.PlanWorkRequest(
            work_planning.WorkIntent(
                request=body.request.strip(),
                creator_id=user.id,
                title=body.title,
            )
        )
    )
    if planned.plan is None:
        # 非多步（单动作/步数不足/解析失败）→ 无计划，前端提示走普通任务卡。
        return ok({"plan": None, "reason": planned.reason})
    return ok(
        {
            "plan": {
                "title": planned.plan.intent.title,
                "request": planned.plan.intent.request,
                "steps": [_step_dict(step) for step in planned.plan.steps],
            },
            "reason": None,
        }
    )


@router.post("/execute")
async def execute_ai_task(body: _ExecuteRequest, db: DB, user: CurrentUser) -> dict:
    """执行真人已确认的计划：客户端回传步骤重建 WorkflowPlan（复校 DAG）→ 既有 start_workflow。

    红线停点由 runtime 的 is_red_line 逐步判定保证：对外/业务/资金/人事步骤停 waiting_human。
    """
    intent = work_planning.WorkIntent(
        request=body.request.strip(),
        creator_id=user.id,  # 服务端锁定创建人，禁止客户端冒充
        title=body.title,
    )
    try:
        plan = work_planning.WorkflowPlan(
            intent=intent,
            steps=tuple(
                work_planning.WorkflowPlanStep(
                    number=step.number,
                    title=step.title,
                    capability_key=step.capability_key,
                    instruction=step.instruction,
                    depends_on=tuple(step.depends_on),
                )
                for step in body.steps
            ),
        )
    except ValueError as exc:  # DAG 无环/依赖合法性等结构校验失败 → 400
        raise RuleViolation(f"计划非法：{exc}") from exc

    started = await task_management.start_workflow(
        db,
        workflow_runtime.planning_to_start_command(plan),
    )
    return ok(await task_management.orchestration_progress(db, started.parent_task_id))
