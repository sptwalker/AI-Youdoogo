"""Outer adapters from Proposal-owned ports to current platform capabilities."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.business.proposal_management.application.contracts import (
    ProposalViewer,
    TaskResult,
)
from app.contexts.business.proposal_management.application.errors import (
    ProposalExpertUnavailable,
    ProposalNotFound,
)
from app.contexts.business.proposal_management.application.ports import (
    AuditRequest,
    ExpertReference,
    ExpertResearchRequest,
    ExpertResearchResult,
    ProposalVisibility,
    TaskCreationRequest,
)
from app.contexts.business.proposal_management.domain.models import Proposal
from app.contexts.business.task_management import public as task_management
from app.contexts.foundations.execution.agent_execution import (
    public as agent_execution,
)
from app.contexts.foundations.governance.ai_quality import public as ai_quality
from app.contexts.foundations.governance.audit_trail import public as audit_trail
from app.contexts.foundations.workforce.expert_management import (
    public as expert_management,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.platform.deterministic import UUIDIdentifier as PlatformUUIDIdentifier


class ProposalIdentifier(PlatformUUIDIdentifier):
    """在通用标识符之上补充提案编号规则（本 Context 特有）。"""

    def new_proposal_code(self) -> str:
        return f"PROP-{uuid.uuid4().hex[:8].upper()}"


class CurrentProposalVisibilityPolicy:
    """Preserve current admin/executive and creator/department visibility semantics."""

    _PRIVILEGED = frozenset({"admin", "executive"})

    def visibility_for(self, viewer: ProposalViewer | None) -> ProposalVisibility:
        if viewer is None or viewer.role_code in self._PRIVILEGED:
            return ProposalVisibility(unrestricted=True)
        return ProposalVisibility(
            unrestricted=False,
            viewer_id=viewer.id,
            department_id=viewer.department_id,
        )

    def ensure_visible(self, viewer: ProposalViewer | None, proposal: Proposal) -> None:
        if viewer is None or viewer.role_code in self._PRIVILEGED:
            return
        if proposal.creator_id == viewer.id:
            return
        if proposal.department_id is not None and proposal.department_id == viewer.department_id:
            return
        raise ProposalNotFound("资源不存在")


class LegacyExpertResearchAdapter:
    """Normalize the current Agent/reflection runtime behind a Proposal-owned port."""

    _RUBRIC = "预研应准确评估提案的可行性、收益与风险，逻辑严谨、不遗漏关键点、不编造。"

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._experts = expert_management.build_local_expert_directory_port(session)
        self._snapshots: dict[uuid.UUID, ExpertExecutionSnapshot] = {}

    async def find_expert(self, name: str) -> ExpertReference | None:
        snapshot = await expert_management.get_expert_execution_by_name(
            self._session,
            name,
        )
        if snapshot is None:
            return None
        self._snapshots[snapshot.expert_id] = snapshot
        return ExpertReference(id=snapshot.expert_id, name=snapshot.name)

    async def research(
        self, expert: ExpertReference, request: ExpertResearchRequest
    ) -> ExpertResearchResult:
        snapshot = self._snapshots.get(expert.id)
        if snapshot is None:
            snapshot = await self._experts.get_execution(expert.id)
        if snapshot is None:
            raise ProposalExpertUnavailable()

        execution = await agent_execution.run_agent_snapshot(
            self._session,
            snapshot,
            task_type=request.task_type,
            input_summary=request.input_summary,
            user_message=request.user_message,
            user_id=request.operator_id,
        )
        draft = (
            execution.content
            or (execution.error.message if execution.error is not None else None)
            or "（无产出）"
        )
        reflection = await ai_quality.review_output(
            self._session,
            ai_quality.OutputReviewRequest(
                expert_id=snapshot.expert_id,
                output=draft,
                task_context=request.user_message,
                rubric=self._RUBRIC,
                user_id=request.operator_id,
            ),
        )
        conclusion = reflection.final_output
        if reflection.revised:
            conclusion += (
                f"\n\n> 系统：本预研经 AI 自查修订（初评 {reflection.critic_score}/5）。"
            )
        return ExpertResearchResult(conclusion=conclusion)


class PublishedTaskCreationAdapter:
    """Translate a Proposal Task request to Task Management's published operation."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_task(self, request: TaskCreationRequest) -> TaskResult:
        task = await task_management.create_task_in_transaction(
            self._session,
            task_management.CreateTaskRequest(
                title=request.title,
                task_type=request.task_type,
                creator_id=request.creator_id,
                priority=request.priority,
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


class PublishedAuditAdapter:
    """Preserve best-effort audit evidence through the current audit facility."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, request: AuditRequest) -> None:
        await audit_trail.append_audit_record(
            self._session,
            audit_trail.AppendAuditRecordCommand(
                actor_id=request.actor_id,
                actor_role=request.actor_role,
                action=request.action,
                summary=request.summary,
                target_type=request.target_type,
                target_id=request.target_id,
            ),
        )
