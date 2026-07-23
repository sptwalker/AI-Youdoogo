"""Outer adapters from Proposal-owned ports to current platform capabilities."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

import app.agents.base as agent_runtime
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
from app.models.agent import AgentRole
from app.services import audit_service, reflection_service, task_service


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class UUIDIdentifier:
    def new_id(self) -> uuid.UUID:
        return uuid.uuid4()

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
        self._roles: dict[uuid.UUID, AgentRole] = {}

    async def find_expert(self, name: str) -> ExpertReference | None:
        role = await agent_runtime.get_agent_role(self._session, name)
        if role is None:
            return None
        self._roles[role.id] = role
        return ExpertReference(id=role.id, name=role.name)

    async def research(
        self, expert: ExpertReference, request: ExpertResearchRequest
    ) -> ExpertResearchResult:
        role = self._roles.get(expert.id)
        if role is None:
            role = await self._session.get(AgentRole, expert.id)
        if role is None or role.is_delete or not role.is_active:
            raise ProposalExpertUnavailable()

        record = await agent_runtime.run_agent(
            self._session,
            role,
            task_type=request.task_type,
            input_summary=request.input_summary,
            user_message=request.user_message,
            user_id=request.operator_id,
        )
        draft = record.output_content or record.error_msg or "（无产出）"
        reflection = await reflection_service.reflect(
            self._session,
            role,
            output=draft,
            task_context=request.user_message,
            rubric=self._RUBRIC,
            user_id=request.operator_id,
        )
        conclusion = reflection.final_output
        if reflection.revised:
            conclusion += (
                f"\n\n> 系统：本预研经 AI 自查修订（初评 {reflection.critic_score}/5）。"
            )
        return ExpertResearchResult(conclusion=conclusion)


class LegacyTaskCreationAdapter:
    """Translate a plain Task request to the current Task compatibility API."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_task(self, request: TaskCreationRequest) -> TaskResult:
        task = await task_service.create_task(
            self._session,
            title=request.title,
            task_type=request.task_type,
            creator_id=request.creator_id,
            priority=request.priority,
            assignee_agent_id=request.assignee_agent_id,
            payload=dict(request.payload),
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


class LegacyAuditAdapter:
    """Preserve best-effort audit evidence through the current audit facility."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(self, request: AuditRequest) -> None:
        await audit_service.audit(
            self._session,
            actor_id=request.actor_id,
            actor_role=request.actor_role,
            action=request.action,
            summary=request.summary,
            target_type=request.target_type,
            target_id=request.target_id,
        )
