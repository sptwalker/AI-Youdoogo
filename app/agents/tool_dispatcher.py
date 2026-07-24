"""Legacy ToolDispatcher adapter over clean Capability Execution."""

from __future__ import annotations

import json
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext, SkillExecutor, SkillRequest, SkillResult
from app.agents.skill_registry import REGISTRY, Skill, enabled_skills, flag_on
from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
)
from app.contexts.foundations.execution.capability_catalog.infrastructure.registry import (
    InMemoryCapabilityCatalog,
)
from app.contexts.foundations.execution.capability_execution.application.ports import (
    HandlerExecutionResult,
)
from app.contexts.foundations.execution.capability_execution.application.use_cases import (
    CapabilityExecutionApplication,
)
from app.contexts.foundations.execution.capability_execution.contracts.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionStatus,
    CapabilityPrincipal,
    CapabilityTrace,
)
from app.contexts.foundations.execution.capability_execution.infrastructure.current_policy import (
    CurrentCapabilityApproval,
    CurrentCapabilityAuthorization,
)
from app.contexts.foundations.execution.capability_execution.infrastructure.sqlalchemy_uow import (
    SQLAlchemyCapabilityExecutionUnitOfWork,
)
from app.models.agent import AgentRole

logger = logging.getLogger(__name__)


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_dict(value: str) -> dict[str, object]:
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


class _BoundCatalog:
    """Expose only catalog definitions with a concrete current runtime binding."""

    def __init__(self, executor: SkillExecutor | None) -> None:
        self._executor = executor
        self._catalog = InMemoryCapabilityCatalog()

    async def resolve(
        self, key: str, version: str | None
    ) -> CapabilityDefinition | None:
        if self._executor is None:
            return None
        return await self._catalog.resolve(key, version)


class _LegacyHandlerAdapter:
    def __init__(
        self,
        session: AsyncSession,
        role: AgentRole,
        context: ExecutionContext,
        executor: SkillExecutor | None,
    ) -> None:
        self._session = session
        self._role = role
        self._context = context
        self._executor = executor
        self.last_result: SkillResult | None = None

    async def execute(
        self,
        request: CapabilityExecutionRequest,
        definition: CapabilityDefinition,
    ) -> HandlerExecutionResult:
        del definition
        if self._executor is None:
            raise LookupError(f"Capability handler {request.capability_key} is unavailable")
        legacy_request = SkillRequest(
            skill_key=request.capability_key,
            action_index=request.action_index,
            arguments=_json_dict(request.arguments_json),
            raw_text=request.raw_text,
        )
        self.last_result = await self._executor.execute(
            self._session,
            self._role,
            legacy_request,
            self._context,
        )
        return HandlerExecutionResult(
            notes=tuple(self.last_result.notes),
            dataset_json=tuple(_json_dump(item) for item in self.last_result.datasets),
            artifact_json=tuple(_json_dump(item) for item in self.last_result.artifacts),
        )


class ToolDispatcher:
    """Preserve legacy calls while delegating structured actions to the use case."""

    def __init__(self, registry: dict[str, Skill] | None = None) -> None:
        self.registry = registry or REGISTRY

    def _executor(self, request: SkillRequest) -> SkillExecutor | None:
        descriptor = self.registry.get(request.skill_key)
        if descriptor is None or descriptor.executor_factory is None:
            return None
        return descriptor.executor_factory()

    async def dispatch(
        self,
        db: AsyncSession,
        role: AgentRole,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult:
        active_context = context.model_copy(update={"dispatcher": self})
        executor = self._executor(request)
        handler = _LegacyHandlerAdapter(db, role, active_context, executor)
        idempotency_key = None
        if executor is not None and executor.requires_idempotency(request):
            idempotency_key = active_context.action_key(
                request.skill_key,
                request.action_index,
            )
        capability_request = CapabilityExecutionRequest(
            capability_key=request.skill_key,
            capability_version="1.0",
            action_index=request.action_index,
            arguments_json=_json_dump(request.arguments),
            raw_text=request.raw_text,
            principal=CapabilityPrincipal(
                principal_id=active_context.user_id,
                expert_id=role.id,
                permission_keys=tuple(
                    item for item in (role.tools or []) if isinstance(item, str)
                ),
            ),
            trace=CapabilityTrace(
                trace_id=active_context.trace_id,
                workflow_run_id=active_context.workflow_run_id,
                workflow_step_id=active_context.workflow_step_id,
                attempt=active_context.attempt,
            ),
            idempotency_key=idempotency_key,
        )
        result = await CapabilityExecutionApplication(
            catalog=_BoundCatalog(executor),
            authorization=CurrentCapabilityAuthorization(),
            approval=CurrentCapabilityApproval(),
            uow=SQLAlchemyCapabilityExecutionUnitOfWork(db),
            handler=handler,
        ).execute(capability_request)

        if result.status is CapabilityExecutionStatus.REJECTED:
            return SkillResult(notes=[f"技能「{request.skill_key}」未注册，动作已拒绝"])
        if result.status is CapabilityExecutionStatus.FAILED:
            logger.warning(
                "结构化技能执行失败 skill=%s error=%s",
                request.skill_key,
                result.error.message if result.error else "unknown",
            )
            return SkillResult(notes=[f"技能「{request.skill_key}」执行失败，已记录"])

        legacy = handler.last_result or SkillResult(
            notes=list(result.notes),
            datasets=[_json_dict(item) for item in result.dataset_json],
            artifacts=[_json_dict(item) for item in result.artifact_json],
        )
        if result.invocation_id is not None:
            legacy.tool_execution_ids.append(result.invocation_id)
        return legacy

    async def dispatch_text(
        self,
        db: AsyncSession,
        role: AgentRole,
        output: str,
        context: ExecutionContext,
        *,
        exclude: set[str] | None = None,
    ) -> SkillResult:
        excluded = set(context.excluded_skills)
        excluded.update(exclude or set())
        merged = SkillResult()
        active_context = context.model_copy(
            update={
                "dispatcher": self,
                "excluded_skills": frozenset(excluded),
            }
        )
        for skill in enabled_skills(role):
            if skill.key in excluded or skill.legacy_executor is None:
                continue
            try:
                if not await flag_on(db, skill):
                    continue
                merged.merge(
                    await skill.legacy_executor(db, role, output, active_context, excluded)
                )
            except Exception:  # noqa: BLE001 - legacy protocol isolation is observable behavior
                logger.warning("技能执行失败 skill=%s", skill.key, exc_info=True)
        return merged
