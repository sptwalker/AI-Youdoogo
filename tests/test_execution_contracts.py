"""Clean Expert, Agent, and Capability execution boundary tests."""

from __future__ import annotations

import dataclasses
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from app.contexts.foundations.execution.agent_execution.application.ports import (
    AgentExecutionRecorderPort,
    ExecutionClock,
    KnowledgeAugmentationPort,
    LlmExecutionPort,
    PromptAssemblyPort,
    UsageAuthorizationPort,
)
from app.contexts.foundations.execution.agent_execution.application.use_cases import (
    AgentExecutionApplication,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    ExecutionError,
    ExecutionTrace,
    KnowledgeAugmentation,
    LlmExecutionRequest,
    LlmExecutionResponse,
    LlmStreamChunk,
    SourceReference,
    TokenUsage,
)
from app.contexts.foundations.execution.capability_catalog.contracts.definition import (
    CapabilityDefinition,
    CapabilityRisk,
    CapabilitySideEffect,
)
from app.contexts.foundations.execution.capability_execution.application.ports import (
    ApprovalDecision,
    AuthorizationDecision,
    CapabilityApprovalPort,
    CapabilityAuthorizationPort,
    CapabilityCatalogPort,
    CapabilityExecutionUnitOfWork,
    CapabilityHandlerPort,
    CapabilityInvocationPort,
    HandlerExecutionResult,
    InvocationClaim,
)
from app.contexts.foundations.execution.capability_execution.application.use_cases import (
    CapabilityExecutionApplication,
)
from app.contexts.foundations.execution.capability_execution.contracts.execution import (
    CapabilityExecutionRequest,
    CapabilityExecutionResult,
    CapabilityExecutionStatus,
    CapabilityPrincipal,
    CapabilityTrace,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)

ROOT = Path(__file__).resolve().parents[1]


def _expert() -> ExpertExecutionSnapshot:
    return ExpertExecutionSnapshot(
        expert_id=uuid.uuid4(),
        version="2026-07-23T00:00:00+00:00",
        name="运营专家",
        title="总监",
        department_id=uuid.uuid4(),
        prompt_template="只依据事实分析。",
        model_role="reasoning",
        capability_keys=("data_query",),
        permission_entries=(("scope", "department"),),
    )


def test_execution_contracts_are_frozen_and_framework_independent() -> None:
    snapshot = _expert()
    with pytest.raises(dataclasses.FrozenInstanceError):
        snapshot.name = "mutated"  # type: ignore[misc]

    roots = (
        ROOT / "app/contexts/foundations/workforce/expert_management/contracts",
        ROOT / "app/contexts/foundations/workforce/expert_management/application",
        ROOT / "app/contexts/foundations/execution/agent_execution/contracts",
        ROOT / "app/contexts/foundations/execution/agent_execution/application",
        ROOT / "app/contexts/foundations/execution/capability_catalog/contracts",
        ROOT / "app/contexts/foundations/execution/capability_catalog/application",
        ROOT / "app/contexts/foundations/execution/capability_execution/contracts",
        ROOT / "app/contexts/foundations/execution/capability_execution/application",
    )
    forbidden = (
        "AsyncSession",
        "sqlalchemy",
        "fastapi",
        "app.models",
        "app.agents",
        "app.services",
        "Callable",
        "Any",
    )
    violations = [
        f"{path.relative_to(ROOT)} contains {token}"
        for root in roots
        for path in sorted(root.rglob("*.py"))
        for token in forbidden
        if token in path.read_text(encoding="utf-8")
    ]
    assert violations == []


class _Prompt(PromptAssemblyPort):
    async def build(self, expert: ExpertExecutionSnapshot) -> str:
        return f"SYSTEM::{expert.prompt_template}"


class _Knowledge(KnowledgeAugmentationPort):
    async def augment(
        self, expert: ExpertExecutionSnapshot, user_message: str
    ) -> KnowledgeAugmentation:
        return KnowledgeAugmentation(
            message=f"KB::{user_message}",
            sources=(SourceReference("file-1", "资料.txt", 2),),
        )


class _UsageAuthorization(UsageAuthorizationPort):
    def __init__(self, error: ExecutionError | None = None) -> None:
        self.error = error

    def authorize(self, request: AgentExecutionRequest) -> ExecutionError | None:
        return self.error


class _Llm(LlmExecutionPort):
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.requests: list[LlmExecutionRequest] = []

    async def invoke(self, request: LlmExecutionRequest) -> LlmExecutionResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return LlmExecutionResponse(
            content="完成",
            model="fake-model",
            usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
        )

    def stream(self, request: LlmExecutionRequest) -> AsyncIterator[LlmStreamChunk]:
        self.requests.append(request)

        async def _items() -> AsyncIterator[LlmStreamChunk]:
            yield LlmStreamChunk(delta="完", accumulated_content="完")
            yield LlmStreamChunk(
                delta="成",
                accumulated_content="完成",
                model="fake-model",
                usage=TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5),
            )

        return _items()


class _Recorder(AgentExecutionRecorderPort):
    def __init__(self) -> None:
        self.results: list[AgentExecutionResult] = []

    async def record(
        self, request: AgentExecutionRequest, result: AgentExecutionResult
    ) -> AgentExecutionResult:
        recorded = dataclasses.replace(result, execution_id=uuid.uuid4())
        self.results.append(recorded)
        return recorded


class _Clock(ExecutionClock):
    def __init__(self) -> None:
        self.value = 1000

    def monotonic_ms(self) -> int:
        self.value += 25
        return self.value


def _agent_request(*, use_knowledge: bool = True) -> AgentExecutionRequest:
    trace = ExecutionTrace(
        trace_id=uuid.uuid4(),
        workflow_run_id=uuid.uuid4(),
        workflow_step_id=uuid.uuid4(),
        attempt=2,
    )
    return AgentExecutionRequest(
        expert=_expert(),
        task_type="analysis",
        input_summary="分析日报",
        user_message="请分析",
        user_id=uuid.uuid4(),
        use_knowledge=use_knowledge,
        trace=trace,
    )


async def test_agent_application_preserves_usage_sources_trace_and_streaming() -> None:
    llm = _Llm()
    recorder = _Recorder()
    app = AgentExecutionApplication(
        prompt_port=_Prompt(),
        knowledge_port=_Knowledge(),
        usage_authorization=_UsageAuthorization(),
        llm_port=llm,
        recorder=recorder,
        clock=_Clock(),
    )
    request = _agent_request()

    result = await app.execute(request)

    assert result.status is AgentExecutionStatus.SUCCEEDED
    assert result.content == "完成"
    assert result.usage.total_tokens == 5
    assert result.sources[0].file_name == "资料.txt"
    assert result.trace == request.trace
    assert result.execution_id is not None
    assert llm.requests[0].user_message == "KB::请分析"

    events = [event async for event in app.stream(request)]
    assert [event.delta for event in events[:-1]] == ["完", "成"]
    assert events[-1].result is not None
    assert events[-1].result.content == "完成"
    assert events[-1].result.usage.total_tokens == 5


async def test_agent_application_records_failure_without_raising() -> None:
    recorder = _Recorder()
    app = AgentExecutionApplication(
        prompt_port=_Prompt(),
        knowledge_port=_Knowledge(),
        usage_authorization=_UsageAuthorization(),
        llm_port=_Llm(error=TimeoutError("boom")),
        recorder=recorder,
        clock=_Clock(),
    )

    result = await app.execute(_agent_request(use_knowledge=False))

    assert result.status is AgentExecutionStatus.FAILED
    assert result.error is not None and "boom" in result.error.message
    assert recorder.results == [result]


class _Catalog(CapabilityCatalogPort):
    def __init__(self, definition: CapabilityDefinition | None) -> None:
        self.definition = definition

    async def resolve(self, key: str, version: str | None) -> CapabilityDefinition | None:
        if self.definition is None or self.definition.key != key:
            return None
        if version is not None and version != self.definition.version:
            return None
        return self.definition


class _Authorization(CapabilityAuthorizationPort):
    async def authorize(
        self, request: CapabilityExecutionRequest, definition: CapabilityDefinition
    ) -> AuthorizationDecision:
        return AuthorizationDecision(allowed=True)


class _Approval(CapabilityApprovalPort):
    async def check(
        self, request: CapabilityExecutionRequest, definition: CapabilityDefinition
    ) -> ApprovalDecision:
        return ApprovalDecision(approved=True)


class _Invocations(CapabilityInvocationPort):
    def __init__(self, replay: CapabilityExecutionResult | None = None) -> None:
        self.replay = replay
        self.claimed = 0
        self.completed = 0
        self.failed = 0

    async def claim(self, request: CapabilityExecutionRequest) -> InvocationClaim:
        self.claimed += 1
        return InvocationClaim(invocation_id=uuid.uuid4(), replay_result=self.replay)

    async def succeed(
        self, invocation_id: uuid.UUID, result: CapabilityExecutionResult
    ) -> None:
        self.completed += 1

    async def fail(self, invocation_id: uuid.UUID, error_message: str) -> None:
        self.failed += 1


class _Uow(CapabilityExecutionUnitOfWork):
    def __init__(self, invocations: _Invocations) -> None:
        self._invocations = invocations
        self.commits = 0
        self.rollbacks = 0

    @property
    def invocations(self) -> CapabilityInvocationPort:
        return self._invocations

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _Handler(CapabilityHandlerPort):
    def __init__(self) -> None:
        self.calls = 0

    async def execute(
        self, request: CapabilityExecutionRequest, definition: CapabilityDefinition
    ) -> HandlerExecutionResult:
        self.calls += 1
        return HandlerExecutionResult(
            output_json='{"ok":true}',
            notes=("done",),
            artifact_json=('{"id":"artifact-1"}',),
        )


def _capability_request() -> CapabilityExecutionRequest:
    return CapabilityExecutionRequest(
        capability_key="deliver",
        capability_version="1.0",
        action_index=0,
        arguments_json='{"name":"日报"}',
        principal=CapabilityPrincipal(
            principal_id=uuid.uuid4(),
            expert_id=uuid.uuid4(),
            permission_keys=("deliver",),
        ),
        trace=CapabilityTrace(trace_id=uuid.uuid4(), attempt=1),
        idempotency_key="workflow:step:deliver:0",
    )


def _definition() -> CapabilityDefinition:
    return CapabilityDefinition(
        key="deliver",
        version="1.0",
        label="文件交付",
        description="生成交付文件",
        input_schema_json='{"type":"object"}',
        output_schema_json='{"type":"object"}',
        risk=CapabilityRisk.MEDIUM,
        side_effect=CapabilitySideEffect.EXTERNAL_WRITE,
        permission_keys=("deliver",),
        handler_identity="legacy.deliver",
    )


async def test_capability_application_commits_claim_and_result() -> None:
    invocations = _Invocations()
    uow = _Uow(invocations)
    handler = _Handler()
    app = CapabilityExecutionApplication(
        catalog=_Catalog(_definition()),
        authorization=_Authorization(),
        approval=_Approval(),
        uow=uow,
        handler=handler,
    )

    result = await app.execute(_capability_request())

    assert result.status is CapabilityExecutionStatus.SUCCEEDED
    assert result.notes == ("done",)
    assert result.audit_correlation_id is not None
    assert handler.calls == 1
    assert invocations.claimed == invocations.completed == 1
    assert uow.commits == 2


async def test_capability_application_reuses_idempotent_result() -> None:
    replay = CapabilityExecutionResult(
        status=CapabilityExecutionStatus.SUCCEEDED,
        capability_key="deliver",
        capability_version="1.0",
        notes=("cached",),
    )
    invocations = _Invocations(replay)
    uow = _Uow(invocations)
    handler = _Handler()
    app = CapabilityExecutionApplication(
        catalog=_Catalog(_definition()),
        authorization=_Authorization(),
        approval=_Approval(),
        uow=uow,
        handler=handler,
    )

    result = await app.execute(_capability_request())

    assert result.replayed is True
    assert result.notes == ("cached",)
    assert handler.calls == 0
    assert uow.commits == 0
