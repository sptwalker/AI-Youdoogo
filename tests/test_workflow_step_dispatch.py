"""P3-2 逐步部门派发：规划器解析可选 expert、运行时逐步写入/缺省回落、翻译层端到端透传。"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from app.contexts.foundations.execution.work_planning.application.use_cases import (
    parse_workflow_plan,
)
from app.contexts.foundations.execution.work_planning.contracts.planning import (
    PlanWorkRequest,
    WorkflowPlan,
    WorkflowPlanStep,
    WorkIntent,
)
from app.contexts.foundations.execution.workflow_runtime.application.planning_translation import (
    planning_to_start_command,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WorkflowLaunchStep,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    sqlalchemy_repository as repo,
)
from app.models.workflow import WorkflowRun


def _request() -> PlanWorkRequest:
    return PlanWorkRequest(WorkIntent(request="月度经营报告", creator_id=uuid.UUID(int=0)))


def test_parser_reads_optional_expert_per_step() -> None:
    """规划器可为不同步指定不同部门（expert UUID）；缺省/非法 → None 回落。"""
    sales, finance = uuid.uuid4(), uuid.uuid4()
    raw = json.dumps(
        {
            "multi": True,
            "steps": [
                {"no": 0, "title": "取销售", "skill": "data_query",
                 "instruction": "查销售", "expert": str(sales)},
                {"no": 1, "title": "取财务", "skill": "data_query",
                 "instruction": "查财务", "expert": str(finance)},
                {"no": 2, "title": "汇总", "skill": "deliver",
                 "instruction": "汇总", "depends_on": [0, 1], "expert": "not-a-uuid"},
            ],
        }
    )
    result = parse_workflow_plan(raw, _request())
    assert result.plan is not None
    steps = result.plan.steps
    assert steps[0].assignee_expert_id == sales
    assert steps[1].assignee_expert_id == finance
    assert steps[0].assignee_expert_id != steps[1].assignee_expert_id  # 不同步派不同部门
    assert steps[2].assignee_expert_id is None  # 非法 UUID 优雅回落，不拒整份计划


def _new_workflow(run_expert: uuid.UUID | None) -> repo._NewWorkflow:
    run = WorkflowRun(id=uuid.uuid4(), assignee_agent_id=run_expert)
    return repo._NewWorkflow(run=run, parent_task_id=uuid.uuid4(), occurred_at=datetime.now(UTC))


def test_new_workflow_step_prefers_step_expert() -> None:
    """运行时逐步写入各自 expert：step 自带 expert 优先于 run 的单一 assignee。"""
    run_expert, step_expert = uuid.uuid4(), uuid.uuid4()
    workflow = _new_workflow(run_expert)
    spec = WorkflowLaunchStep(0, "取数", "data_query", "查", assignee_expert_id=step_expert)
    step_id = uuid.uuid4()
    result = repo._new_workflow_step(workflow, spec, step_id, uuid.uuid4(), {0: step_id}, False)
    assert result.assignee_agent_id == step_expert

    event = repo._step_created_progress(workflow, spec, step_id, uuid.uuid4(), (), False)
    assert event.payload["expert_id"] == str(step_expert)


def test_new_workflow_step_falls_back_to_run_assignee() -> None:
    """缺省回落不破坏既有单派发：step 无 expert → 用 run 的 assignee。"""
    run_expert = uuid.uuid4()
    workflow = _new_workflow(run_expert)
    spec = WorkflowLaunchStep(0, "取数", "data_query", "查")  # assignee_expert_id 缺省 None
    step_id = uuid.uuid4()
    result = repo._new_workflow_step(workflow, spec, step_id, uuid.uuid4(), {0: step_id}, False)
    assert result.assignee_agent_id == run_expert

    event = repo._step_created_progress(workflow, spec, step_id, uuid.uuid4(), (), False)
    assert event.payload["expert_id"] == str(run_expert)


def test_translation_threads_per_step_expert_into_command() -> None:
    """翻译层把逐步 expert 端到端透传进 StartWorkflowCommand.steps（不触 DB）。"""
    sales, finance = uuid.uuid4(), uuid.uuid4()
    plan = WorkflowPlan(
        WorkIntent(request="月报", creator_id=uuid.uuid4()),
        (
            WorkflowPlanStep(0, "取销售", "data_query", "查销售", assignee_expert_id=sales),
            WorkflowPlanStep(1, "取财务", "data_query", "查财务", assignee_expert_id=finance),
        ),
    )
    command = planning_to_start_command(plan)
    assert [step.assignee_expert_id for step in command.steps] == [sales, finance]
