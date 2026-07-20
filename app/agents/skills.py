"""强类型技能注册表、结构化调度器与旧中文指令兼容入口。

Agent Runtime 只依赖本模块暴露的 dispatcher；具体技能通过工厂延迟加载，技能 service
不再反向 import ``agents.base``。未来原生 tool calling 与 LangGraph 节点可直接提交
``SkillRequest``，现有文本输出仍由各技能的 legacy adapter 转成相同请求。
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.contracts import (
    ExecutionContext,
    SkillExecutor,
    SkillRequest,
    SkillResult,
)
from app.models.agent import AgentRole
from app.services import config_service, tool_execution_service

__all__ = [
    "REGISTRY",
    "Skill",
    "ToolDispatcher",
    "enabled_skills",
    "execute_all",
    "fold_notes",
    "prompt_sections",
]

logger = logging.getLogger(__name__)


LegacyExecutor = Callable[
    [AsyncSession, AgentRole, str, ExecutionContext, set[str]],
    Awaitable[SkillResult],
]


@dataclass(frozen=True)
class Skill:
    """技能描述符：提示词元数据与执行器注册位于同一事实源。"""

    key: str
    label: str
    description: str
    flag_key: str
    default_on: bool = True
    executor_factory: Callable[[], SkillExecutor] | None = None
    legacy_executor: LegacyExecutor | None = None


def _collab_executor() -> SkillExecutor:
    from app.services.collab_protocol import CollabSkillExecutor

    return CollabSkillExecutor()


def _deliver_executor() -> SkillExecutor:
    from app.services.deliver_service import DeliverySkillExecutor

    return DeliverySkillExecutor()


def _query_executor() -> SkillExecutor:
    from app.services.query_skill import DataQuerySkillExecutor

    return DataQuerySkillExecutor()


def _accepted_kwargs(call: Any, values: dict[str, Any]) -> dict[str, Any]:
    """只传目标函数声明过的兼容参数，便于旧插件和测试桩渐进迁移。"""
    try:
        params = inspect.signature(call).parameters
    except (TypeError, ValueError):
        return values
    if any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values()):
        return values
    return {key: value for key, value in values.items() if key in params}


async def _legacy_collab(
    db: AsyncSession,
    role: AgentRole,
    output: str,
    context: ExecutionContext,
    _exclude: set[str],
) -> SkillResult:
    from app.services import collab_protocol

    kwargs = _accepted_kwargs(
        collab_protocol.execute,
        {"user_id": context.user_id, "execution_context": context},
    )
    return await collab_protocol.execute(db, role, output, **kwargs)


async def _legacy_deliver(
    db: AsyncSession,
    role: AgentRole,
    output: str,
    context: ExecutionContext,
    _exclude: set[str],
) -> SkillResult:
    from app.services import deliver_service

    kwargs = _accepted_kwargs(
        deliver_service.execute,
        {"user_id": context.user_id, "execution_context": context},
    )
    return await deliver_service.execute(db, role, output, **kwargs)


async def _legacy_query(
    db: AsyncSession,
    role: AgentRole,
    output: str,
    context: ExecutionContext,
    exclude: set[str],
) -> SkillResult:
    from app.services import query_skill

    kwargs = _accepted_kwargs(
        query_skill.execute,
        {
            "user_id": context.user_id,
            "user_intent": context.user_intent,
            "exclude": exclude,
            "execution_context": context,
        },
    )
    return await query_skill.execute(db, role, output, **kwargs)


REGISTRY: dict[str, Skill] = {
    "env_context": Skill(
        "env_context",
        "环境快照",
        "感知组织架构/AI花名册/真人用户/数据接口",
        "agent_env_context",
    ),
    "collab": Skill(
        "collab",
        "协作原语",
        "咨询其他AI + 发起跨部门协作（真人复核生效）",
        "agent_collab_protocol",
        executor_factory=_collab_executor,
        legacy_executor=_legacy_collab,
    ),
    "deliver": Skill(
        "deliver",
        "文件交付",
        "把产出整理成CSV/XLSX/文档交付到工作桌面",
        "agent_deliver",
        executor_factory=_deliver_executor,
        legacy_executor=_legacy_deliver,
    ),
    "data_query": Skill(
        "data_query",
        "数据取数",
        "用只读SQL查运营数据（护栏校验+审计）",
        "agent_data_query",
        executor_factory=_query_executor,
        legacy_executor=_legacy_query,
    ),
}


def enabled_skills(role: AgentRole) -> list[Skill]:
    """该 AI 启用的技能。tools 空为默认全开；非空只保留注册 key。"""
    tools = [item for item in (role.tools or []) if isinstance(item, str)]
    if not (role.tools or []):
        return [skill for skill in REGISTRY.values() if skill.default_on]
    return [REGISTRY[key] for key in tools if key in REGISTRY]


async def _flag_on(db: AsyncSession, skill: Skill) -> bool:
    flag = await config_service.resolve(db, skill.flag_key, True)
    return str(flag).lower() not in ("false", "0")


async def _section(db: AsyncSession, skill: Skill) -> str:
    if skill.key == "env_context":
        from app.services.environment_service import get_env_context

        snapshot = await get_env_context(db)
        if not snapshot:
            return ""
        return f"\n\n【系统环境快照】（由系统档案员维护，实时数据，可直接引用）\n{snapshot}"
    if skill.key == "collab":
        from app.services.collab_protocol import PROMPT_SECTION

        return PROMPT_SECTION
    if skill.key == "deliver":
        from app.services.deliver_service import PROMPT_SECTION

        return PROMPT_SECTION
    if skill.key == "data_query":
        from app.services.query_skill import prompt_section

        return await prompt_section(db)
    return ""


async def prompt_sections(db: AsyncSession, role: AgentRole) -> str:
    """拼接启用技能的提示词段；单技能故障不阻断 Agent。"""
    parts: list[str] = []
    for skill in enabled_skills(role):
        try:
            if await _flag_on(db, skill):
                parts.append(await _section(db, skill))
        except Exception:  # noqa: BLE001 - 单技能注入故障不阻断
            logger.warning("技能提示词段注入失败 skill=%s", skill.key, exc_info=True)
    return "".join(parts)


def _stored_result(data: dict[str, Any]) -> SkillResult:
    """从 ToolExecution 的 JSON 结果恢复可复用部分。"""
    return SkillResult(
        notes=list(data.get("notes") or []),
        datasets=list(data.get("datasets") or []),
        artifacts=list(data.get("artifacts") or []),
    )


def _result_data(result: SkillResult) -> dict[str, Any]:
    """ToolExecution 只保存 JSON 安全部分；Agent 记录通过 trace 字段单独关联。"""
    return {
        "notes": result.notes,
        "datasets": result.datasets,
        "artifacts": result.artifacts,
    }


class ToolDispatcher:
    """结构化技能调度器：注册校验、幂等记录、失败收敛与结果复用。"""

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
        """执行一个已结构化动作；未注册动作默认拒绝，绝不授予审批类能力。"""
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
            await db.commit()  # 外部副作用前，幂等记录必须已持久化

        try:
            result = await executor.execute(db, role, request, context)
        except Exception as exc:  # noqa: BLE001 - 单个技能失败不打断消息/工作流收尾
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
        """运行旧文本兼容层；每个 adapter 内部生成并提交 SkillRequest。"""
        excluded = exclude or set()
        merged = SkillResult()
        active_context = context.model_copy(update={"dispatcher": self})
        for skill in enabled_skills(role):
            if skill.key in excluded or skill.legacy_executor is None:
                continue
            try:
                if not await _flag_on(db, skill):
                    continue
                merged.merge(
                    await skill.legacy_executor(db, role, output, active_context, excluded)
                )
            except Exception:  # noqa: BLE001 - 技能协议故障不连累其余技能
                logger.warning("技能执行失败 skill=%s", skill.key, exc_info=True)
        return merged


async def execute_all(
    db: AsyncSession,
    role: AgentRole,
    output: str,
    *,
    user_id: UUID | None = None,
    user_intent: str | None = None,
    exclude: set[str] | None = None,
    execution_context: ExecutionContext | None = None,
) -> SkillResult:
    """兼容旧调用点的统一文本入口，并透传持久化执行上下文。"""
    context = execution_context or ExecutionContext(
        user_id=user_id,
        user_intent=user_intent,
    )
    updates: dict[str, Any] = {}
    if context.user_id is None and user_id is not None:
        updates["user_id"] = user_id
    if context.user_intent is None and user_intent is not None:
        updates["user_intent"] = user_intent
    if updates:
        context = context.model_copy(update=updates)
    dispatcher = ToolDispatcher()
    return await dispatcher.dispatch_text(db, role, output, context, exclude=exclude)


def fold_notes(text: str, result: SkillResult) -> str:
    """把技能执行注记折进正文。"""
    if not result.notes:
        return text
    return text + "\n\n" + "\n".join(f"> 系统：{note}" for note in result.notes)
