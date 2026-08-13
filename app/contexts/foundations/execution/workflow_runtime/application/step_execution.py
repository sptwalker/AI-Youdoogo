"""Explicit Claim, Prepare, Execute, and Finalize workflow collaborators."""

from __future__ import annotations

from typing import cast

from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    ExecutionTrace,
)
from app.contexts.foundations.execution.workflow_runtime.application.ports import (
    ExpertSnapshotPort,
    WorkflowAgentExecutionPort,
    WorkflowCapabilityExecutionPort,
    WorkflowLeaseHeartbeatPort,
    WorkflowUnitOfWorkFactory,
)
from app.contexts.foundations.execution.workflow_runtime.contracts.runtime import (
    ClaimWorkflowStepCommand,
    ClaimWorkflowStepResult,
    ExecuteWorkflowStepResult,
    FinalizeWorkflowStepCommand,
    FinalizeWorkflowStepResult,
    PreparedWorkflowStep,
    PrepareWorkflowStepCommand,
    StepClaimStatus,
    StepExecutionDisposition,
)
from app.contexts.foundations.execution.workflow_runtime.domain.policies import (
    is_mechanical,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)

# 机械发布步跳过 LLM：合成一个空的成功执行结果喂能力端口（机械分支忽略此结果内容）。
_MECHANICAL_AGENT_RESULT = AgentExecutionResult(
    status=AgentExecutionStatus.SUCCEEDED, trace=ExecutionTrace()
)


class ClaimWorkflowStep:
    def __init__(self, units: WorkflowUnitOfWorkFactory) -> None:
        self._units = units

    async def execute(self, command: ClaimWorkflowStepCommand) -> ClaimWorkflowStepResult:
        async with self._units() as unit:
            result = await unit.workflows.claim(command)
            if result.status == StepClaimStatus.CLAIMED:
                await unit.commit()
            else:
                await unit.rollback()
            return result


class PrepareWorkflowStep:
    def __init__(
        self,
        units: WorkflowUnitOfWorkFactory,
        experts: ExpertSnapshotPort,
    ) -> None:
        self._units = units
        self._experts = experts

    async def execute(self, command: PrepareWorkflowStepCommand) -> PreparedWorkflowStep:
        async with self._units() as unit:
            prepared = await unit.workflows.prepare(command.claim)
            expert = (
                await self._experts.get_by_id(command.claim.expert_id)
                if command.claim.expert_id is not None
                else None
            )
            await unit.commit()
        return PreparedWorkflowStep(
            claim=prepared.claim,
            trace_id=prepared.trace_id,
            creator_id=prepared.creator_id,
            request_text=prepared.request_text,
            title=prepared.title,
            capability_key=prepared.capability_key,
            instruction=prepared.instruction,
            expert=expert,
            input_data=prepared.input_data,
        )


class ExecuteWorkflowStep:
    def __init__(
        self,
        agents: WorkflowAgentExecutionPort,
        capabilities: WorkflowCapabilityExecutionPort,
    ) -> None:
        self._agents = agents
        self._capabilities = capabilities

    async def execute(self, prepared: PreparedWorkflowStep) -> ExecuteWorkflowStepResult:
        if is_mechanical(prepared.capability_key):
            # 机械发布步：真人已验收上游 compose 草稿，本步不调 LLM，直接做不可逆对外写。
            return await self._capabilities.execute(prepared, _MECHANICAL_AGENT_RESULT)
        if prepared.expert is None:
            return ExecuteWorkflowStepResult(
                succeeded=False,
                content="步骤无可用执行者",
                error="步骤无可用执行者",
            )
        agent_result = await self._agents.execute(
            AgentExecutionRequest(
                expert=cast(ExpertExecutionSnapshot, prepared.expert),
                task_type=prepared.capability_key,
                input_summary=f"持久化步骤：{prepared.title[:40]}",
                user_message=render_step_message(prepared),
                user_id=prepared.creator_id,
                use_knowledge=True,
                trace=ExecutionTrace(
                    trace_id=prepared.trace_id,
                    workflow_run_id=prepared.claim.workflow_id,
                    workflow_step_id=prepared.claim.step_id,
                    attempt=prepared.claim.attempt,
                ),
            )
        )
        if agent_result.status == AgentExecutionStatus.FAILED:
            return ExecuteWorkflowStepResult(
                succeeded=False,
                content=agent_result.content or "（无产出）",
                agent_execution_id=agent_result.execution_id,
                error=agent_result.error.message if agent_result.error else "Agent 执行失败",
            )
        return await self._capabilities.execute(prepared, agent_result)


class FinalizeWorkflowStep:
    def __init__(self, units: WorkflowUnitOfWorkFactory) -> None:
        self._units = units

    async def execute(
        self, command: FinalizeWorkflowStepCommand
    ) -> FinalizeWorkflowStepResult:
        async with self._units() as unit:
            result = await unit.workflows.finalize(command)
            if result.applied:
                await unit.commit()
            else:
                await unit.rollback()
            return result


class WorkflowStepExecutionApplication:
    """Keep external work between a committed claim and fenced finalization."""

    def __init__(
        self,
        *,
        claim: ClaimWorkflowStep,
        prepare: PrepareWorkflowStep,
        execute: ExecuteWorkflowStep,
        finalize: FinalizeWorkflowStep,
        heartbeat: WorkflowLeaseHeartbeatPort | None = None,
    ) -> None:
        self._claim = claim
        self._prepare = prepare
        self._execute = execute
        self._finalize = finalize
        self._heartbeat = heartbeat

    async def run(self, command: ClaimWorkflowStepCommand) -> StepExecutionDisposition:
        claim_result = await self._claim.execute(command)
        if claim_result.status == StepClaimStatus.BUSY:
            return StepExecutionDisposition(
                kind="defer",
                retry_at=claim_result.retry_at,
                reason="workflow step lease is still active",
            )
        if claim_result.status == StepClaimStatus.TERMINAL or claim_result.claim is None:
            return StepExecutionDisposition(kind="complete")
        prepared = await self._prepare.execute(
            PrepareWorkflowStepCommand(claim_result.claim)
        )
        if self._heartbeat is None:
            execution = await self._execute.execute(prepared)
        else:
            async with self._heartbeat.keep_alive(prepared.claim):
                execution = await self._execute.execute(prepared)
        finalization = await self._finalize.execute(
            FinalizeWorkflowStepCommand(prepared, execution)
        )
        if not finalization.applied:
            raise RuntimeError("workflow step finalization was rejected as stale")
        return StepExecutionDisposition(kind="complete", finalization=finalization)


def render_step_message(prepared: PreparedWorkflowStep) -> str:
    data = dict(prepared.input_data)
    parts = [f"任务：{prepared.title}", f"要求：{prepared.instruction}"]
    datasets = data.get("datasets")
    if isinstance(datasets, (list, tuple)) and datasets:
        parts.append("\n上游步骤已取得以下结构化数据，请只依据真实数据继续：")
        parts.extend(str(dataset)[:12000] for dataset in datasets)
    artifacts = data.get("artifacts")
    if isinstance(artifacts, (list, tuple)) and artifacts:
        names = "、".join(
            str(item.get("file_name", ""))
            for item in artifacts
            if isinstance(item, dict)
        )
        parts.append(f"\n上游文件引用：{names}")
    parts.append("\n请完成本步骤；需要数据、咨询或交付时使用已启用技能。")
    return "\n".join(parts)
