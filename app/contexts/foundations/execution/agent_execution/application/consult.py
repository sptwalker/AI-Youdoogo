"""Application orchestration for a read-only expert consultation."""

from __future__ import annotations

from app.contexts.foundations.execution.agent_execution.application.ports import (
    AgentExecutionPort,
    ExpertSnapshotPort,
)
from app.contexts.foundations.execution.agent_execution.contracts.consult import (
    ConsultExpertCommand,
    ConsultExpertResult,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
)
from app.contexts.shared_kernel import ResourceNotFound


class ConsultExpert:
    def __init__(
        self,
        *,
        experts: ExpertSnapshotPort,
        executions: AgentExecutionPort,
    ) -> None:
        self._experts = experts
        self._executions = executions

    async def execute(self, command: ConsultExpertCommand) -> ConsultExpertResult:
        expert = await self._experts.get_by_id(command.expert_id)
        if expert is None:
            raise ResourceNotFound("AI 顾问不存在或已停用")
        conversation = "\n".join(
            f"{'我' if turn.role == 'user' else expert.name}：{turn.content}"
            for turn in command.history[-6:]
        )
        message = (
            f"以下是我们的对话：\n{conversation}\n\n我：{command.message}"
            if conversation
            else command.message
        )
        result = await self._executions.execute(
            AgentExecutionRequest(
                expert=expert,
                task_type="desktop_consult",
                input_summary=f"对话：{command.message[:40]}",
                user_message=message,
                user_id=command.user_id,
                use_knowledge=True,
            )
        )
        return ConsultExpertResult(
            reply=(
                result.content
                or (result.error.message if result.error is not None else None)
                or "（无回应）"
            ),
            status=result.status.value,
            execution_id=result.execution_id,
        )
