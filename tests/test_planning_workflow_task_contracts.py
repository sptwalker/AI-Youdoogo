"""Pure contract and orchestration tests for Planning, Workflow, and Task contexts."""

from __future__ import annotations

import ast
import dataclasses
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Self, cast

import pytest

from app.contexts.business.task_management.contracts.tasks import (
    TASK_DECISION_RECORDED_V1,
    TaskDecisionRecordedV1,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionResult,
    AgentExecutionStatus,
    ExecutionTrace,
)
from app.contexts.foundations.execution.work_planning.application.use_cases import (
    PlanWorkApplication,
)
from app.contexts.foundations.execution.work_planning.contracts.planning import (
    PlanWorkRequest,
    WorkflowPlan,
    WorkflowPlanStep,
    WorkIntent,
)
from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    WorkflowUnitOfWorkFactory,
)
from app.contexts.foundations.execution.workflow_runtime.application.step_execution import (
    ClaimWorkflowStep,
    ExecuteWorkflowStep,
    FinalizeWorkflowStep,
    PrepareWorkflowStep,
    WorkflowStepExecutionApplication,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    WORKFLOW_PROGRESSED_V1,
    ClaimedWorkflowStep,
    ClaimWorkflowStepCommand,
    ClaimWorkflowStepResult,
    ExecuteWorkflowStepResult,
    FinalizeWorkflowStepResult,
    PreparedWorkflowStep,
    StartWorkflowCommand,
    StepClaimStatus,
    WorkflowLaunchStep,
    WorkflowProgressedV1,
    WorkflowRunStatus,
    WorkflowStepStatus,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)

ROOT = Path(__file__).resolve().parents[1]


def _intent() -> WorkIntent:
    return WorkIntent(request="先查询昨日数据，再生成日报", creator_id=uuid.uuid4())


def test_work_intent_and_plan_are_immutable_and_validate_dag() -> None:
    intent = _intent()
    plan = WorkflowPlan(
        intent=intent,
        steps=(
            WorkflowPlanStep(0, "查询", "data_query", "查询昨日数据"),
            WorkflowPlanStep(1, "日报", "deliver", "生成日报", (0,)),
        ),
    )

    assert PlanWorkRequest(intent).intent is intent
    command = StartWorkflowCommand(
        creator_id=intent.creator_id,
        request=intent.request,
        steps=(
            WorkflowLaunchStep(0, "查询", "data_query", "查询昨日数据"),
            WorkflowLaunchStep(1, "日报", "deliver", "生成日报", (0,)),
        ),
    )
    assert command.steps[1].depends_on == (0,)
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.steps[0].title = "changed"  # type: ignore[misc]
    with pytest.raises(ValueError, match="acyclic"):
        WorkflowPlan(
            intent=intent,
            steps=(
                WorkflowPlanStep(0, "A", "other", "A", (1,)),
                WorkflowPlanStep(1, "B", "other", "B", (0,)),
            ),
        )


def test_workflow_and_task_events_are_versioned_plain_values() -> None:
    now = datetime.now(UTC)
    workflow_id = uuid.uuid4()
    step_id = uuid.uuid4()
    task_id = uuid.uuid4()
    creator_id = uuid.uuid4()
    principal_id = uuid.uuid4()
    progressed = WorkflowProgressedV1(
        event_id=uuid.uuid4(),
        workflow_id=workflow_id,
        run_version=2,
        occurred_at=now,
        transition="step.waiting_human",
        run_status=WorkflowRunStatus.WAITING_HUMAN,
        business_key=str(task_id),
        payload={
            "parent_task_id": str(uuid.uuid4()),
            "creator_id": str(creator_id),
            "title": "日报流程",
            "request_text": "生成日报",
            "task_card_id": str(task_id),
        },
        step_id=step_id,
        step_version=3,
    )
    decision = TaskDecisionRecordedV1(
        event_id=uuid.uuid4(),
        task_id=task_id,
        workflow_id=workflow_id,
        workflow_step_id=step_id,
        expected_step_version=3,
        decision="accepted",
        principal_id=principal_id,
        occurred_at=now,
    )

    assert WORKFLOW_PROGRESSED_V1.endswith(".v1")
    assert TASK_DECISION_RECORDED_V1.endswith(".v1")
    assert progressed.step_version == decision.expected_step_version
    assert dataclasses.is_dataclass(progressed) and dataclasses.is_dataclass(decision)


def test_runtime_event_names_no_product_fields() -> None:
    """ADR 0005：运行时事件不得具名产品概念，产品数据只能藏在不透明 payload。"""
    product_tokens = {
        "parent_task_id",
        "creator_id",
        "title",
        "request_text",
        "task_card_id",
        "step_title",
        "capability_key",
        "instruction",
        "red_line",
        "expert_id",
        "depends_on_task_ids",
        "result_content",
    }
    field_names = {f.name for f in dataclasses.fields(WorkflowProgressedV1)}
    assert field_names & product_tokens == set()
    assert {"business_key", "payload"} <= field_names


def test_runtime_contract_imports_no_cross_context_types() -> None:
    """ADR 0007：运行时契约不得具名 import 任何别的 Context 产品类型（自身/shared_kernel 除外）。"""
    path = ROOT / "app/contexts/foundations/execution/workflow_runtime/contracts/runtime.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    leaks = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module is not None
        and node.module.startswith("app.contexts.")
        and "workflow_runtime" not in node.module
        and "shared_kernel" not in node.module
    }
    assert leaks == set(), leaks


def test_new_execution_contracts_do_not_import_framework_or_orm_modules() -> None:
    roots = (
        ROOT / "app/contexts/foundations/execution/work_planning/contracts",
        ROOT / "app/contexts/foundations/execution/workflow_runtime/contracts",
        ROOT / "app/contexts/business/task_management/contracts",
    )
    forbidden = ("sqlalchemy", "fastapi", "app.models", "app.services", "app.agents")
    for root in roots:
        for path in root.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert not any(token in source for token in forbidden), path


async def test_planning_application_only_asks_model_and_returns_a_plan() -> None:
    class FakePlanningModel:
        calls = 0

        async def propose(self, intent: WorkIntent) -> str:
            self.calls += 1
            assert intent.request == "先查询昨日数据，再生成日报"
            return (
                '{"multi":true,"steps":['
                '{"no":0,"title":"查询","skill":"data_query",'
                '"instruction":"查询昨日数据","depends_on":[]},'
                '{"no":1,"title":"日报","skill":"deliver",'
                '"instruction":"生成日报","depends_on":[0]}]}'
            )

    model = FakePlanningModel()
    result = await PlanWorkApplication(model).execute(PlanWorkRequest(_intent()))

    assert model.calls == 1
    assert result.plan is not None
    assert result.plan.steps[1].depends_on == (0,)


async def test_step_execution_orders_four_phases_and_closes_transactions() -> None:
    events: list[str] = []
    workflow_id = uuid.uuid4()
    step_id = uuid.uuid4()
    worker_id = "worker-a"
    claim = ClaimedWorkflowStep(
        workflow_id=workflow_id,
        step_id=step_id,
        task_card_id=uuid.uuid4(),
        expert_id=uuid.uuid4(),
        worker_id=worker_id,
        attempt=2,
        version=7,
        lease_until=datetime.now(UTC),
    )
    expert = ExpertExecutionSnapshot(
        expert_id=claim.expert_id,  # type: ignore[arg-type]
        version="v1",
        name="运营专家",
        title="",
        department_id=None,
        prompt_template="执行",
        model_role="daily",
    )

    class Repository:
        async def claim(self, command: ClaimWorkflowStepCommand) -> ClaimWorkflowStepResult:
            events.append("claim")
            assert command.step_id == step_id
            return ClaimWorkflowStepResult(StepClaimStatus.CLAIMED, claim)

        async def prepare(self, current: ClaimedWorkflowStep) -> PreparedWorkflowStep:
            events.append("prepare")
            return PreparedWorkflowStep(
                claim=current,
                trace_id=uuid.uuid4(),
                creator_id=uuid.uuid4(),
                request_text="生成日报",
                title="生成日报",
                capability_key="deliver",
                instruction="生成日报",
                expert=None,
            )

        async def finalize(self, command: object) -> FinalizeWorkflowStepResult:
            events.append("finalize")
            return FinalizeWorkflowStepResult(
                True, workflow_id, step_id, WorkflowStepStatus.SUCCEEDED, 8
            )

    class Unit:
        def __init__(self) -> None:
            self.workflows = Repository()

        async def __aenter__(self) -> Self:
            events.append("uow.enter")
            return self

        async def __aexit__(self, *args: object) -> None:
            events.append("uow.exit")

        async def commit(self) -> None:
            events.append("commit")

        async def rollback(self) -> None:
            events.append("rollback")

    class Units:
        def __call__(self) -> Unit:
            return Unit()

    class Experts:
        async def get_by_id(self, expert_id: uuid.UUID) -> ExpertExecutionSnapshot | None:
            events.append("expert_snapshot")
            assert expert_id == claim.expert_id
            return expert

    class Agents:
        async def execute(self, request: object) -> AgentExecutionResult:
            events.append("agent_execute")
            return AgentExecutionResult(
                status=AgentExecutionStatus.SUCCEEDED,
                trace=ExecutionTrace(workflow_run_id=workflow_id, workflow_step_id=step_id),
                content="done",
            )

    class Capabilities:
        async def execute(
            self, prepared: PreparedWorkflowStep, agent_result: AgentExecutionResult
        ) -> ExecuteWorkflowStepResult:
            events.append("capability_execute")
            assert prepared.expert is expert and agent_result.content == "done"
            return ExecuteWorkflowStepResult(True, "done")

    units = Units()
    typed_units = cast(WorkflowUnitOfWorkFactory, units)
    application = WorkflowStepExecutionApplication(
        claim=ClaimWorkflowStep(typed_units),
        prepare=PrepareWorkflowStep(typed_units, Experts()),
        execute=ExecuteWorkflowStep(Agents(), Capabilities()),
        finalize=FinalizeWorkflowStep(typed_units),
    )

    disposition = await application.run(
        ClaimWorkflowStepCommand(step_id, worker_id, lease_seconds=60)
    )

    assert disposition.kind == "complete"
    assert events == [
        "uow.enter",
        "claim",
        "commit",
        "uow.exit",
        "uow.enter",
        "prepare",
        "expert_snapshot",
        "commit",
        "uow.exit",
        "agent_execute",
        "capability_execute",
        "uow.enter",
        "finalize",
        "commit",
        "uow.exit",
    ]
