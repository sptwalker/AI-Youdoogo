"""Agent Runtime 与技能层的强类型端口。

此模块只定义数据与 Protocol，不依赖具体 Agent/技能实现，是未来 LangGraph adapter 与当前
DatabaseWorkflowEngine 共用的稳定边界。
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentRole, AgentTaskRecord


class AgentRunner(Protocol):
    """技能调用其他 Agent 时依赖的端口，避免反向 import agents.base。"""

    async def __call__(
        self,
        db: AsyncSession,
        role: AgentRole,
        *,
        task_type: str,
        input_summary: str,
        user_message: str,
        user_id: uuid.UUID | None = None,
        use_knowledge: bool = False,
        execution_context: ExecutionContext | None = None,
    ) -> AgentTaskRecord: ...


class SkillDispatcher(Protocol):
    """文本兼容层与结构化动作共用的技能调度端口。"""

    async def dispatch(
        self,
        db: AsyncSession,
        role: AgentRole,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult: ...

    async def dispatch_text(
        self,
        db: AsyncSession,
        role: AgentRole,
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
    consult_replies: list[tuple[AgentRole, AgentTaskRecord]] = Field(default_factory=list)
    datasets: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    tool_execution_ids: list[uuid.UUID] = Field(default_factory=list)

    def merge(self, other: SkillResult) -> None:
        self.notes.extend(other.notes)
        self.consult_replies.extend(other.consult_replies)
        self.datasets.extend(other.datasets)
        self.artifacts.extend(other.artifacts)
        self.tool_execution_ids.extend(other.tool_execution_ids)


class SkillExecutor(Protocol):
    """可注册技能执行器的统一接口。"""

    key: str

    def requires_idempotency(self, request: SkillRequest) -> bool:
        """该动作是否可能产生外部副作用，需先持久化 ToolExecution。"""
        ...

    async def execute(
        self,
        db: AsyncSession,
        role: AgentRole,
        request: SkillRequest,
        context: ExecutionContext,
    ) -> SkillResult: ...
