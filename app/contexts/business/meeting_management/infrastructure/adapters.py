"""Outer adapters for Access, Agent/Capability advisory work, and Task creation."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext
from app.agents.tool_dispatcher import ToolDispatcher
from app.contexts.business.meeting_management.application.contracts import TaskResult
from app.contexts.business.meeting_management.application.ports import (
    AdvisoryEventKind,
    AdvisoryResult,
    AdvisoryStreamEvent,
    MeetingVisibility,
    MinutesAdvisoryRequest,
    SpeechAdvisoryRequest,
    TaskCreationRequest,
    VoteAdvisoryRequest,
)
from app.contexts.business.meeting_management.domain.models import Meeting
from app.contexts.business.task_management import public as task_management
from app.contexts.foundations.access_control.contracts import PolicyDecision
from app.contexts.foundations.execution.agent_execution import (
    public as agent_execution,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
)
from app.contexts.foundations.identity.contracts import Principal
from app.contexts.foundations.workforce.expert_management import (
    public as expert_management,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.shared_kernel import ResourceNotFound, RuleViolation

EXPERT_NAME = "会商AI专家"


class AccessControlMeetingVisibilityPolicy:
    """Translate Access Control's published decision into Meeting query intent."""

    _PRIVILEGED_ROLES = frozenset({"admin", "executive"})

    def visibility_for(self, principal: Principal | None) -> MeetingVisibility:
        if principal is None:
            return MeetingVisibility(unrestricted=True)
        if principal.role_code in self._PRIVILEGED_ROLES:
            return MeetingVisibility(unrestricted=True)
        return MeetingVisibility(
            unrestricted=False,
            creator_id=principal.principal_id,
            department_id=principal.department_id,
        )

    def ensure_visible(self, principal: Principal | None, meeting: Meeting) -> None:
        if principal is None:
            return
        decision = self._decide(principal, meeting)
        if not decision.allowed:
            raise ResourceNotFound(decision.reason)

    def _decide(self, principal: Principal, meeting: Meeting) -> PolicyDecision:
        if principal.role_code in self._PRIVILEGED_ROLES:
            return PolicyDecision(allowed=True)
        if meeting.creator_id == principal.principal_id:
            return PolicyDecision(allowed=True)
        if meeting.department_id is not None and meeting.department_id == principal.department_id:
            return PolicyDecision(allowed=True)
        return PolicyDecision(
            allowed=False,
            reason="资源不存在",
            conceal_resource=True,
        )


class LegacyMeetingAdvisoryAdapter:
    """Keep current Agent and capability behavior behind a pure Meeting port."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def speak(self, request: SpeechAdvisoryRequest) -> AsyncIterator[AdvisoryStreamEvent]:
        expert = await self._expert_required()
        context = "\n".join(f"{name}：{content}" for name, content in request.history)
        context = context or "（暂无发言）"
        user_message = (
            f"这是一场决策会议，议题：{request.topic}\n\n已有发言：\n{context}\n\n"
            "请以会商AI专家身份发表一段简明分析意见（利弊、风险、建议），供与会真人参考。"
        )
        yield AdvisoryStreamEvent(
            kind=AdvisoryEventKind.STARTED,
            expert_id=expert.expert_id,
            expert_name=expert.name,
        )
        execution_result: AgentExecutionResult | None = None
        async for event in agent_execution.stream_agent(
            self._session,
            AgentExecutionRequest(
                expert=expert,
                task_type="meeting_discuss",
                input_summary=f"会议发言：{request.topic[:40]}",
                user_message=user_message,
                user_id=request.operator_id,
            ),
        ):
            if event.delta is not None:
                yield AdvisoryStreamEvent(
                    kind=AdvisoryEventKind.DELTA,
                    expert_id=expert.expert_id,
                    expert_name=expert.name,
                    text=event.delta,
                )
            elif event.result is not None:
                execution_result = event.result
        if execution_result is None:
            raise RuntimeError("Agent stream completed without a result")
        content = execution_result.output_content or execution_result.error_msg or "（无产出）"
        result = await ToolDispatcher().dispatch_text(
            self._session,
            expert,
            content,
            ExecutionContext(
                user_id=request.operator_id,
                agent_runner=agent_execution.run_agent_snapshot,
            ),
            user_id=request.operator_id,
        )
        content = result.fold_notes(content)
        yield AdvisoryStreamEvent(
            kind=AdvisoryEventKind.COMPLETED,
            expert_id=expert.expert_id,
            expert_name=expert.name,
            text=content,
        )
        for consulted, consult_record in result.consult_replies:
            answer = consult_record.output_content or consult_record.error_msg or "（无回应）"
            yield AdvisoryStreamEvent(
                kind=AdvisoryEventKind.STARTED,
                expert_id=consulted.expert_id,
                expert_name=consulted.name,
            )
            yield AdvisoryStreamEvent(
                kind=AdvisoryEventKind.DELTA,
                expert_id=consulted.expert_id,
                expert_name=consulted.name,
                text=answer,
            )
            yield AdvisoryStreamEvent(
                kind=AdvisoryEventKind.COMPLETED,
                expert_id=consulted.expert_id,
                expert_name=consulted.name,
                text=answer,
            )

    async def vote(self, request: VoteAdvisoryRequest) -> AdvisoryResult:
        expert = await self._expert_required()
        execution = await agent_execution.run_agent_snapshot(
            self._session,
            expert,
            task_type="meeting_vote",
            input_summary=f"AI参考票：{request.subject[:40]}",
            user_message=(
                f"就以下表决事项给出你的参考意见：{request.subject}\n"
                "第一行只输出 approve / reject / abstain 之一，第二行给一句理由。"
            ),
            user_id=request.operator_id,
        )
        return AdvisoryResult(
            expert_id=expert.expert_id,
            expert_name=expert.name,
            content=execution.output_content or "",
            comment=execution.output_content,
        )

    async def minutes(self, request: MinutesAdvisoryRequest) -> AdvisoryResult:
        expert = await self._expert_required()
        body = "\n".join(
            f"{name}（{speaker_type}）：{content}"
            for name, speaker_type, content in request.discussions
        )
        execution = await agent_execution.run_agent_snapshot(
            self._session,
            expert,
            task_type="meeting_minutes",
            input_summary=f"会议纪要：{request.title[:40]}",
            user_message=(
                f"会议主题：{request.title}\n\n以下是全部发言，请生成结构化会议纪要"
                f"（含【议题】【主要观点】【分歧点】【建议决议】）：\n\n{body}"
            ),
            user_id=request.operator_id,
        )
        return AdvisoryResult(
            expert_id=expert.expert_id,
            expert_name=expert.name,
            content=execution.output_content or execution.error_msg or "（无产出）",
        )

    async def _expert_required(self) -> ExpertExecutionSnapshot:
        expert = await expert_management.get_expert_execution_by_name(
            self._session,
            EXPERT_NAME,
        )
        if expert is None:
            raise RuleViolation("未配置会商AI专家角色，请先执行数据库迁移（alembic upgrade head）")
        return expert


class TaskManagementCreationAdapter:
    """Translate Meeting-owned Task intent to Task Management's published operation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_task(self, request: TaskCreationRequest) -> TaskResult:
        task = await task_management.create_task_in_transaction(
            self._session,
            task_management.CreateTaskRequest(
                title=request.title,
                task_type=request.task_type,
                creator_id=request.creator_id,
                assignee_agent_id=request.assignee_agent_id,
                payload=request.payload,
            ),
        )
        return TaskResult(
            id=task.id,
            title=task.title,
            task_type=task.task_type,
            priority=task.priority,
            status=task.status,
            creator_id=task.creator_id,
            assignee_agent_id=task.assignee_agent_id,
            parent_id=task.parent_id,
            sla_hours=task.sla_hours,
            result_content=task.result_content,
            create_time=task.create_time,
        )
