"""Framework-independent Agent execution request, result, and trace."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import StrEnum

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest as LlmExecutionRequest,
)
from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionResponse as LlmExecutionResponse,
)
from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionStreamChunk as LlmStreamChunk,
)
from app.contexts.foundations.model_gateway.contracts.completion import TokenUsage
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)

# Canonical LLM completion contracts now live in model_gateway; these names are
# preserved here as aliases so existing agent_execution imports/tests stay unchanged.
__all__ = [
    "AgentExecutionRequest",
    "AgentExecutionResult",
    "AgentExecutionStatus",
    "AgentExecutionStreamEvent",
    "CapabilityActivity",
    "ContextReference",
    "EvidenceReference",
    "ExecutionError",
    "ExecutionTrace",
    "KnowledgeAugmentation",
    "LlmExecutionRequest",
    "LlmExecutionResponse",
    "LlmStreamChunk",
    "ReflectionOutcome",
    "SourceReference",
    "TokenUsage",
]


class AgentExecutionStatus(StrEnum):
    SUCCEEDED = "success"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExecutionTrace:
    trace_id: uuid.UUID | None = None
    workflow_run_id: uuid.UUID | None = None
    workflow_step_id: uuid.UUID | None = None
    attempt: int | None = None


@dataclass(frozen=True, slots=True)
class ContextReference:
    context: str
    identifier: str
    version: str | None = None


@dataclass(frozen=True, slots=True)
class SourceReference:
    file_id: str
    file_name: str
    chunk_index: int


@dataclass(frozen=True, slots=True)
class EvidenceReference:
    kind: str
    reference: str
    label: str = ""


@dataclass(frozen=True, slots=True)
class CapabilityActivity:
    capability_key: str
    status: str
    invocation_id: uuid.UUID | None = None


@dataclass(frozen=True, slots=True)
class ReflectionOutcome:
    score: int | None = None
    revised: bool = False
    issues: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionError:
    code: str
    message: str
    retryable: bool = False


@dataclass(frozen=True, slots=True)
class KnowledgeAugmentation:
    message: str
    sources: tuple[SourceReference, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentExecutionRequest:
    expert: ExpertExecutionSnapshot
    task_type: str
    input_summary: str
    user_message: str
    user_id: uuid.UUID | None = None
    use_knowledge: bool = False
    trace: ExecutionTrace = ExecutionTrace()
    context_references: tuple[ContextReference, ...] = ()


@dataclass(frozen=True, slots=True)
class AgentExecutionResult:
    status: AgentExecutionStatus
    trace: ExecutionTrace
    content: str | None = None
    execution_id: uuid.UUID | None = None
    model: str | None = None
    duration_ms: int = 0
    usage: TokenUsage = TokenUsage()
    sources: tuple[SourceReference, ...] = ()
    evidence: tuple[EvidenceReference, ...] = ()
    capability_activity: tuple[CapabilityActivity, ...] = ()
    reflection: ReflectionOutcome | None = None
    error: ExecutionError | None = None

    @property
    def id(self) -> uuid.UUID | None:
        """Compatibility alias for callers migrating from AgentTaskRecord."""
        return self.execution_id

    @property
    def output_content(self) -> str | None:
        """Compatibility alias for callers migrating from AgentTaskRecord."""
        return self.content

    @property
    def error_msg(self) -> str | None:
        """Compatibility alias for callers migrating from AgentTaskRecord."""
        return self.error.message if self.error is not None else None


@dataclass(frozen=True, slots=True)
class AgentExecutionStreamEvent:
    delta: str | None = None
    result: AgentExecutionResult | None = None
