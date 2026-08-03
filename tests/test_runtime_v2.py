"""Runtime v2 contracts, anti-corruption translation, and routing tests."""

from __future__ import annotations

import dataclasses
import uuid
from pathlib import Path
from typing import Self, cast

import pytest

from app.contexts.foundations.execution.work_planning.contracts.planning import (
    PlanningContextReference,
    WorkflowPlan,
    WorkflowPlanStep,
    WorkIntent,
)
from app.contexts.foundations.execution.workflow_runtime.application.planning_translation import (
    planning_to_runtime_v2,
    planning_to_start_command,
)
from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    WorkflowUnitOfWorkFactory,
)
from app.contexts.foundations.execution.workflow_runtime.application.runtime_routing import (
    RoutedRuntimeClient,
    RuntimeAdapterNotConfiguredError,
    RuntimeEngineTakeoverError,
    RuntimeRoutingPolicy,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    StartWorkflowResult,
    WorkflowRunStatus,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime_v2 import (
    RuntimeEngine,
    RuntimeExecutorRef,
    RuntimeInstanceRefV2,
    RuntimeInstanceStatus,
    RuntimeStartResultV2,
    RuntimeStepSubmissionV2,
    RuntimeSubmissionV2,
)
from app.contexts.foundations.execution.workflow_runtime.infrastructure import (
    local_runtime_adapter,
    remote_runtime_adapter,
)

ROOT = Path(__file__).resolve().parents[1]


def _plan() -> WorkflowPlan:
    return WorkflowPlan(
        intent=WorkIntent(
            request="先查询数据，再生成报告",
            title="日报",
            creator_id=uuid.UUID("11111111-1111-1111-1111-111111111111"),
            assignee_expert_id=uuid.UUID("22222222-2222-2222-2222-222222222222"),
            context_references=(PlanningContextReference("project", "p-1", "v3"),),
        ),
        steps=(
            WorkflowPlanStep(0, "查询", "data_query", "查询数据"),
            WorkflowPlanStep(1, "报告", "deliver", "生成报告", (0,)),
        ),
    )


def test_runtime_v2_contract_is_plain_and_independent() -> None:
    source = (
        ROOT / "app/contexts/foundations/execution/workflow_runtime/contracts/runtime_v2.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "WorkflowPlan",
        "ExpertExecutionSnapshot",
        "TaskCard",
        "work_planning",
        "expert_management",
        "task_management",
        "sqlalchemy",
        "fastapi",
        "app.models",
        "app.services",
        "app.agents",
    )
    assert not any(token in source for token in forbidden)
    assert dataclasses.is_dataclass(RuntimeSubmissionV2)


def test_runtime_v2_application_boundary_has_no_outer_runtime_dependencies() -> None:
    application = ROOT / "app/contexts/foundations/execution/workflow_runtime/application"
    files = (
        application / "planning_translation.py",
        application / "runtime_routing.py",
        application / "runtime_v2_ports.py",
    )
    forbidden = ("sqlalchemy", "fastapi", "app.models", "app.services", "app.agents")
    for path in files:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path


def test_runtime_v2_validates_generic_dag_dependencies() -> None:
    executor = RuntimeExecutorRef("capability", "deliver")
    with pytest.raises(ValueError, match="unknown step"):
        RuntimeSubmissionV2(
            business_key="workflow:1",
            workflow_type="durable_dag",
            input_data=(),
            steps=(RuntimeStepSubmissionV2("step:a", executor, depends_on=("missing",)),),
        )
    with pytest.raises(ValueError, match="acyclic"):
        RuntimeSubmissionV2(
            business_key="workflow:1",
            workflow_type="durable_dag",
            input_data=(),
            steps=(
                RuntimeStepSubmissionV2("step:a", executor, depends_on=("step:b",)),
                RuntimeStepSubmissionV2("step:b", executor, depends_on=("step:a",)),
            ),
        )


def test_planning_translation_is_deterministic_and_preserves_dependencies() -> None:
    first = planning_to_runtime_v2(_plan())
    second = planning_to_runtime_v2(_plan())

    assert first == second
    assert first.contract_version == 2
    assert first.business_key.startswith("planning-v1:")
    assert first.workflow_type == "durable_dag"
    assert first.steps[0].business_key == "step:0"
    assert first.steps[1].depends_on == ("step:0",)
    assert first.steps[1].executor_ref == RuntimeExecutorRef("capability", "deliver")


async def test_local_adapter_wraps_existing_start_contract_and_transaction() -> None:
    events: list[str] = []
    workflow_id = uuid.uuid4()
    parent_task_id = uuid.uuid4()
    trace_id = uuid.uuid4()

    class Repository:
        async def start(self, command: object) -> StartWorkflowResult:
            events.append("start")
            assert command == planning_to_start_command(_plan())
            return StartWorkflowResult(
                workflow_id,
                parent_task_id,
                trace_id,
                WorkflowRunStatus.QUEUED,
                0,
            )

    class Unit:
        def __init__(self) -> None:
            self.workflows = Repository()

        async def __aenter__(self) -> Self:
            events.append("enter")
            return self

        async def __aexit__(self, *args: object) -> None:
            events.append("exit")

        async def commit(self) -> None:
            events.append("commit")

        async def rollback(self) -> None:
            events.append("rollback")

    class Units:
        def __call__(self) -> Unit:
            return Unit()

    adapter = local_runtime_adapter.LocalRuntimeAdapter(cast(WorkflowUnitOfWorkFactory, Units()))
    submission = planning_to_runtime_v2(_plan())
    result = await adapter.submit(submission)

    assert events == ["enter", "start", "commit", "exit"]
    assert result.instance == RuntimeInstanceRefV2(
        runtime_id=str(workflow_id),
        business_key=submission.business_key,
        workflow_type="durable_dag",
        engine=RuntimeEngine.LOCAL,
    )
    assert result.status == RuntimeInstanceStatus.QUEUED
    assert dict(result.output_data) == {
        "parent_task_id": str(parent_task_id),
        "trace_id": str(trace_id),
        "version": 0,
    }


async def test_routing_defaults_local_and_pins_existing_instance_engine() -> None:
    calls: list[RuntimeEngine] = []

    class Client:
        def __init__(self, engine: RuntimeEngine) -> None:
            self.engine = engine

        async def submit(self, submission: RuntimeSubmissionV2) -> RuntimeStartResultV2:
            calls.append(self.engine)
            return RuntimeStartResultV2(
                RuntimeInstanceRefV2(
                    runtime_id=f"{self.engine.value}-1",
                    business_key=submission.business_key,
                    workflow_type=submission.workflow_type,
                    engine=self.engine,
                ),
                RuntimeInstanceStatus.QUEUED,
            )

    local = Client(RuntimeEngine.LOCAL)
    remote = Client(RuntimeEngine.REMOTE)
    submission = planning_to_runtime_v2(_plan(), workflow_type="future_remote")

    default_router = RoutedRuntimeClient(local, remote=remote)
    local_result = await default_router.submit(submission)
    assert local_result.instance.engine == RuntimeEngine.LOCAL

    remote_router = RoutedRuntimeClient(
        local,
        remote=remote,
        policy=RuntimeRoutingPolicy({"future_remote": RuntimeEngine.REMOTE}),
    )
    remote_result = await remote_router.submit(submission)
    assert remote_result.instance.engine == RuntimeEngine.REMOTE
    assert calls == [RuntimeEngine.LOCAL, RuntimeEngine.REMOTE]
    assert remote_router.client_for_existing(remote_result.instance) is remote
    with pytest.raises(RuntimeEngineTakeoverError):
        remote_router.client_for_existing(
            remote_result.instance,
            requested_engine=RuntimeEngine.LOCAL,
        )


async def test_remote_branch_is_explicitly_disabled_until_production_gates_pass() -> None:
    submission = planning_to_runtime_v2(_plan(), workflow_type="remote")
    local = remote_runtime_adapter.RemoteRuntimeAdapter()
    with pytest.raises(
        remote_runtime_adapter.RemoteRuntimeNotConfiguredError,
        match="keep routing local",
    ):
        await local.submit(submission)

    router = RoutedRuntimeClient(
        local,
        policy=RuntimeRoutingPolicy({"remote": RuntimeEngine.REMOTE}),
    )
    with pytest.raises(RuntimeAdapterNotConfiguredError, match="remote"):
        await router.submit(submission)
