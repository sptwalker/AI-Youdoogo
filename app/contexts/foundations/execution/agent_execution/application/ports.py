"""Agent-owned ports for volatile execution details."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Protocol

from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStreamEvent,
    ExecutionError,
    KnowledgeAugmentation,
    LlmExecutionRequest,
    LlmExecutionResponse,
    LlmStreamChunk,
)
from app.contexts.foundations.execution.agent_execution.contracts.records import (
    AgentExecutionRecordView,
)
from app.contexts.foundations.execution.capability_execution.contracts.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)


class PromptAssemblyPort(Protocol):
    async def build(self, expert: ExpertExecutionSnapshot) -> str: ...


class KnowledgeAugmentationPort(Protocol):
    async def augment(
        self, expert: ExpertExecutionSnapshot, user_message: str
    ) -> KnowledgeAugmentation: ...


class UsageAuthorizationPort(Protocol):
    def authorize(self, request: AgentExecutionRequest) -> ExecutionError | None: ...


class LlmExecutionPort(Protocol):
    async def invoke(self, request: LlmExecutionRequest) -> LlmExecutionResponse: ...

    def stream(self, request: LlmExecutionRequest) -> AsyncIterator[LlmStreamChunk]: ...


class AgentExecutionRecorderPort(Protocol):
    async def record(
        self, request: AgentExecutionRequest, result: AgentExecutionResult
    ) -> AgentExecutionResult: ...


class ExecutionClock(Protocol):
    def monotonic_ms(self) -> int: ...


class ExternalExecutionBoundaryPort(Protocol):
    async def release_before_external_call(self) -> None: ...


class AgentExecutionPort(Protocol):
    async def execute(self, request: AgentExecutionRequest) -> AgentExecutionResult: ...

    def stream(
        self, request: AgentExecutionRequest
    ) -> AsyncIterator[AgentExecutionStreamEvent]: ...


class ExpertSnapshotPort(Protocol):
    async def get_by_id(self, expert_id: uuid.UUID) -> ExpertExecutionSnapshot | None: ...


class AgentExecutionRecordQueryPort(Protocol):
    async def get(self, execution_id: uuid.UUID) -> AgentExecutionRecordView | None: ...

    async def list_recent(self, limit: int) -> tuple[AgentExecutionRecordView, ...]: ...


class CapabilityExecutionPort(Protocol):
    """Agent-owned view of synchronous capability invocation."""

    async def execute(
        self, request: CapabilityExecutionRequest
    ) -> CapabilityExecutionResult: ...
