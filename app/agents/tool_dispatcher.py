"""Typed skill dispatch with validation, idempotency, and replay."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import ExecutionContext, SkillExecutor, SkillRequest, SkillResult
from app.agents.skill_registry import REGISTRY, Skill, enabled_skills, flag_on
from app.models.agent import AgentRole
from app.services import tool_execution_service

logger = logging.getLogger(__name__)


def _stored_result(data: dict[str, Any]) -> SkillResult:
    return SkillResult(
        notes=list(data.get("notes") or []),
        datasets=list(data.get("datasets") or []),
        artifacts=list(data.get("artifacts") or []),
    )


def _result_data(result: SkillResult) -> dict[str, Any]:
    return {
        "notes": result.notes,
        "datasets": result.datasets,
        "artifacts": result.artifacts,
    }


class ToolDispatcher:
    """Dispatch registered typed skills and reuse completed logical actions."""

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
        executor = self._executor(request)
        if executor is None:
            return SkillResult(notes=[f"技能「{request.skill_key}」未注册，动作已拒绝"])

        key = context.action_key(request.skill_key, request.action_index)
        tool_record = None
        if key and executor.requires_idempotency(request):
            tool_record, replay = await tool_execution_service.begin(
                db,
                tool_key=request.skill_key,
                idempotency_key=key,
                request_data=request.model_dump(mode="json"),
                context=context,
            )
            if replay:
                result = _stored_result(tool_record.result_data or {})
                result.tool_execution_ids.append(tool_record.id)
                return result
            await db.commit()

        try:
            result = await executor.execute(db, role, request, context)
        except Exception as exc:  # noqa: BLE001 - one tool failure must not block finalization
            if tool_record is not None:
                await tool_execution_service.fail(db, tool_record, str(exc))
                await db.commit()
            logger.warning("结构化技能执行失败 skill=%s", request.skill_key, exc_info=True)
            return SkillResult(notes=[f"技能「{request.skill_key}」执行失败，已记录"])

        if tool_record is not None:
            await tool_execution_service.succeed(db, tool_record, _result_data(result))
            await db.commit()
            result.tool_execution_ids.append(tool_record.id)
        return result

    async def dispatch_text(
        self,
        db: AsyncSession,
        role: AgentRole,
        output: str,
        context: ExecutionContext,
        *,
        exclude: set[str] | None = None,
    ) -> SkillResult:
        excluded = exclude or set()
        merged = SkillResult()
        active_context = context.model_copy(update={"dispatcher": self})
        for skill in enabled_skills(role):
            if skill.key in excluded or skill.legacy_executor is None:
                continue
            try:
                if not await flag_on(db, skill):
                    continue
                merged.merge(
                    await skill.legacy_executor(db, role, output, active_context, excluded)
                )
            except Exception:  # noqa: BLE001 - legacy protocols are independently isolated
                logger.warning("技能执行失败 skill=%s", skill.key, exc_info=True)
        return merged
