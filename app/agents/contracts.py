"""Agent Runtime 与技能层的强类型端口。

此模块只定义数据与 Protocol，不依赖具体 Agent/技能实现，是未来 LangGraph adapter 与当前
DatabaseWorkflowEngine 共用的稳定边界。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionResult,
    AgentExecutionStatus,
    ExecutionError,
    ExecutionTrace,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)


@dataclass(frozen=True, slots=True)
class AgentSubject:
    """Pure expert identity and authorization facts used by capability adapters."""

    expert_id: uuid.UUID
    name: str
    title: str = ""
    department_id: uuid.UUID | None = None
    owner_user_id: uuid.UUID | None = None
    capability_keys: tuple[str, ...] = ()
    permission_entries: tuple[tuple[str, str], ...] = ()
    capabilities_configured: bool = False

    @property
    def id(self) -> uuid.UUID:
        """Compatibility alias while legacy capability handlers migrate."""
        return self.expert_id


def agent_subject(value: object) -> AgentSubject:
    """Normalize snapshots and legacy mapped rows at the outer compatibility seam."""
    if isinstance(value, AgentSubject):
        return value
    if isinstance(value, ExpertExecutionSnapshot):
        return AgentSubject(
            expert_id=value.expert_id,
            name=value.name,
            title=value.title,
            department_id=value.department_id,
            owner_user_id=value.owner_user_id,
            capability_keys=value.capability_keys,
            permission_entries=value.permission_entries,
            capabilities_configured=bool(value.capability_keys),
        )
    legacy = cast(Any, value)
    raw_tools = legacy.tools or ()
    raw_permissions = legacy.permission_scope or {}
    return AgentSubject(
        expert_id=legacy.id,
        name=str(legacy.name),
        title=str(legacy.title or ""),
        department_id=legacy.department_id,
        owner_user_id=legacy.owner_user_id,
        capability_keys=tuple(item for item in raw_tools if isinstance(item, str)),
        permission_entries=tuple((str(key), repr(item)) for key, item in raw_permissions.items()),
        capabilities_configured=bool(raw_tools),
    )


def agent_execution_result(value: object) -> AgentExecutionResult:
    """Normalize legacy persisted records into the published execution result."""
    if isinstance(value, AgentExecutionResult):
        return value
    succeeded = str(getattr(value, "status", "success")) == "success"
    error_message = getattr(value, "error_msg", None)
    return AgentExecutionResult(
        status=(AgentExecutionStatus.SUCCEEDED if succeeded else AgentExecutionStatus.FAILED),
        trace=ExecutionTrace(),
        content=getattr(value, "output_content", None),
        execution_id=getattr(value, "id", None),
        model=getattr(value, "model_used", None),
        duration_ms=getattr(value, "duration_ms", 0) or 0,
        error=(
            ExecutionError("execution_failed", str(error_message or "Agent 执行失败"))
            if not succeeded
            else None
        ),
    )


class AgentRunner(Protocol):
    """技能调用其他 Agent 时依赖的端口，避免耦合具体执行组合。"""

    async def __call__(
        self,
        db: AsyncSession,
        role: ExpertExecutionSnapshot,
        *,
        task_type: str,
        input_summary: str,
        user_message: str,
        user_id: uuid.UUID | None = None,
        use_knowledge: bool = False,
        execution_context: ExecutionContext | None = None,
    ) -> AgentExecutionResult: ...


class SkillDispatcher(Protocol):
    """文本兼容层与结构化动作共用的技能调度端口。"""

    async def dispatch(
        self,
        db: AsyncSession,
        role: AgentSubject,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult: ...

    async def dispatch_text(
        self,
        db: AsyncSession,
        role: AgentSubject,
        output: str,
        context: ExecutionContext,
        *,
        exclude: set[str] | None = None,
    ) -> SkillResult: ...


class ExecutionContext(BaseModel):
    """贯穿 workflow、Agent、LLM 和技能执行的关联上下文。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    workflow_run_id: uuid.UUID | None = None
    workflow_step_id: uuid.UUID | None = None
    attempt: int | None = None
    trace_id: uuid.UUID | None = None
    idempotency_prefix: str | None = None
    user_id: uuid.UUID | None = None
    user_intent: str | None = None
    excluded_skills: frozenset[str] = Field(default_factory=frozenset)
    # Protocol 无运行时 class，Pydantic v2 无法为其构造 isinstance validator；保留
    # 静态端口类型在 AgentRunner/SkillDispatcher 定义处，数据模型字段用 Any 承载注入实例。
    agent_runner: Any = None
    dispatcher: Any = None

    def action_key(self, tool_key: str, action_index: int) -> str | None:
        """构造稳定工具幂等键；普通对话无 prefix 时不强行持久化幂等。"""
        if not self.idempotency_prefix:
            return None
        return f"{self.idempotency_prefix}:{tool_key}:{action_index}"


class SkillRequest(BaseModel):
    """经结构化 tool call 或旧文本适配器产生的统一技能请求。"""

    skill_key: str
    action_index: int = Field(ge=0)
    arguments: dict[str, Any] = Field(default_factory=dict)
    raw_text: str | None = None


class SkillResult(BaseModel):
    """技能统一结果：面向人展示、下游步骤与追踪三类数据。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    notes: list[str] = Field(default_factory=list)
    consult_replies: list[tuple[AgentSubject, AgentExecutionResult]] = Field(default_factory=list)
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_execution_ids: list[uuid.UUID] = Field(default_factory=list)

    @field_validator("consult_replies", mode="before")
    @classmethod
    def _normalize_consult_replies(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        normalized: list[tuple[AgentSubject, AgentExecutionResult]] = []
        for item in value:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                normalized.append(item)  # type: ignore[arg-type]
                continue
            normalized.append((agent_subject(item[0]), agent_execution_result(item[1])))
        return normalized

    def merge(self, other: SkillResult) -> None:
        self.notes.extend(other.notes)
        self.consult_replies.extend(other.consult_replies)
        self.datasets.extend(other.datasets)
        self.artifacts.extend(other.artifacts)
        self.tool_execution_ids.extend(other.tool_execution_ids)

    def fold_notes(self, text: str) -> str:
        """Append runtime notes to a user-visible response when present."""
        if not self.notes:
            return text
        return text + "\n\n" + "\n".join(f"> 系统：{note}" for note in self.notes)


class SkillExecutor(Protocol):
    """可注册技能执行器的统一接口。"""

    key: str

    def requires_idempotency(self, request: SkillRequest) -> bool:
        """该动作是否可能产生外部副作用，需先持久化 ToolExecution。"""
        ...

    async def execute(
        self,
        db: AsyncSession,
        role: AgentSubject,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult: ...
