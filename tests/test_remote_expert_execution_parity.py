"""RemoteExpertExecutionAdapter parity（Phase 3 / docs/23 §6.2）——缝在 LlmCompletionPort。

证明：把 ``AgentExecutionApplication`` 的 ``llm_port`` 从本地换成 ``RemoteExpertExecutionAdapter``
（经 httpx.MockTransport 回放专家平台「创建→流式」两步契约），产出的 ``AgentExecutionStreamEvent``
序列与本地逐字相等（deltas + 终块 content/model/usage）。离线：无真服务、无真 LLM、注入 stub token。
再证首块前失败经 FallbackCompletionPort 干净降级本地。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import replace

import httpx

from app.contexts.foundations.execution.agent_execution.application.use_cases import (
    AgentExecutionApplication,
)
from app.contexts.foundations.execution.agent_execution.contracts.execution import (
    AgentExecutionRequest,
    AgentExecutionResult,
    AgentExecutionStatus,
    AgentExecutionStreamEvent,
)
from app.contexts.foundations.execution.agent_execution.infrastructure.remote_execution_adapter import (  # noqa: E501
    RemoteExpertExecutionAdapter,
)
from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
    LlmCompletionResponse,
    LlmCompletionStreamChunk,
    TokenUsage,
)
from app.contexts.foundations.model_gateway.infrastructure.fallback_adapter import (
    FallbackCompletionPort,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)

_BASE = "http://expert.test"
_FIXED_ID = uuid.UUID(int=42)

# 单一脚本 → 本地 chunk 与远端 SSE 帧同源生成，两路必须逐字一致。
_SCRIPT = [
    {"delta": "你", "accumulated": "你", "model": "expert-model", "usage": (0, 0, 0)},
    {"delta": "好", "accumulated": "你好", "model": "expert-model", "usage": (3, 2, 5)},
]


def _snapshot() -> ExpertExecutionSnapshot:
    return ExpertExecutionSnapshot(
        expert_id=uuid.uuid4(),
        version="v1",
        name="助理",
        title="t",
        department_id=None,
        prompt_template="p",
        model_role="daily",
    )


def _request() -> AgentExecutionRequest:
    return AgentExecutionRequest(
        expert=_snapshot(),
        task_type="chat",
        input_summary="i",
        user_message="u",
        use_knowledge=False,
    )


class _FakePrompt:
    async def build(self, expert: ExpertExecutionSnapshot) -> str:
        return "sys"


class _FakeKnowledge:  # 不被调用（use_knowledge=False），补全端口即可
    async def augment(self, expert: object, message: str) -> object:  # pragma: no cover
        raise AssertionError("use_knowledge=False 不应触发知识增强")


class _AllowUsage:
    def authorize(self, request: AgentExecutionRequest) -> None:
        return None


class _FakeRecorder:
    async def record(
        self, request: AgentExecutionRequest, result: AgentExecutionResult
    ) -> AgentExecutionResult:
        # 固定 execution_id + 已由 FixedClock 定死 duration → 两路结果可逐字比对。
        return replace(result, execution_id=_FIXED_ID)


class _FixedClock:
    def monotonic_ms(self) -> int:
        return 0


class _LocalStub:
    """本地 LlmCompletionPort：按 _SCRIPT 发同一 chunk 序列。"""

    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        last = _SCRIPT[-1]
        return LlmCompletionResponse(
            content=last["accumulated"],  # type: ignore[arg-type]
            model=last["model"],  # type: ignore[arg-type]
            usage=TokenUsage(*last["usage"]),  # type: ignore[misc]
        )

    def stream(self, request: LlmCompletionRequest) -> AsyncIterator[LlmCompletionStreamChunk]:
        async def _it() -> AsyncIterator[LlmCompletionStreamChunk]:
            for s in _SCRIPT:
                yield LlmCompletionStreamChunk(
                    delta=s["delta"],  # type: ignore[arg-type]
                    accumulated_content=s["accumulated"],  # type: ignore[arg-type]
                    model=s["model"],  # type: ignore[arg-type]
                    usage=TokenUsage(*s["usage"]),  # type: ignore[misc]
                )

        return _it()


def _sse_body() -> str:
    frames = []
    for s in _SCRIPT:
        p, c, t = s["usage"]  # type: ignore[misc]
        frames.append(
            "data: "
            + json.dumps(
                {
                    "delta": s["delta"],
                    "accumulated_content": s["accumulated"],
                    "model": s["model"],
                    "usage": {"prompt_tokens": p, "completion_tokens": c, "total_tokens": t},
                },
                ensure_ascii=False,
            )
            + "\n\n"
        )
    frames.append("data: [DONE]\n\n")
    return "".join(frames)


def _expert_platform_transport(*, create_status: int = 200) -> httpx.MockTransport:
    """回放专家平台两步契约：POST 创建 → {execution_id}；GET 流式 → SSE。"""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            if create_status != 200:
                return httpx.Response(create_status, json={"error": "down"})
            return httpx.Response(200, json={"execution_id": str(_FIXED_ID)})
        return httpx.Response(200, content=_sse_body().encode("utf-8"))

    return httpx.MockTransport(handle)


def _remote_adapter(**kwargs: object) -> RemoteExpertExecutionAdapter:
    client = httpx.AsyncClient(transport=_expert_platform_transport(**kwargs))  # type: ignore[arg-type]
    return RemoteExpertExecutionAdapter(
        base_url=_BASE, client=client, token_minter=lambda: "stub-token"
    )


def _application(llm_port: object) -> AgentExecutionApplication:
    return AgentExecutionApplication(
        prompt_port=_FakePrompt(),
        knowledge_port=_FakeKnowledge(),
        usage_authorization=_AllowUsage(),
        llm_port=llm_port,  # type: ignore[arg-type]
        recorder=_FakeRecorder(),
        clock=_FixedClock(),
    )


async def _drive(llm_port: object) -> list[AgentExecutionStreamEvent]:
    return [event async for event in _application(llm_port).stream(_request())]


async def test_remote_stream_matches_local() -> None:
    local_events = await _drive(_LocalStub())
    remote_events = await _drive(_remote_adapter())

    # deltas 逐字相等
    assert [e.delta for e in local_events] == [e.delta for e in remote_events]
    # 终块结果 content/model/usage 相等（execution_id/duration 已被 fake 定死）
    local_result = local_events[-1].result
    remote_result = remote_events[-1].result
    assert local_result is not None and remote_result is not None
    assert local_result.status == AgentExecutionStatus.SUCCEEDED
    assert local_result.content == remote_result.content
    assert local_result.model == remote_result.model
    assert local_result.usage == remote_result.usage
    assert remote_result.content == "你好"
    assert remote_result.usage == TokenUsage(3, 2, 5)


async def test_falls_back_before_first_chunk() -> None:
    """远端创建阶段 5xx 耗尽重试（首块前失败）→ FallbackCompletionPort 干净降级本地。"""
    port = FallbackCompletionPort(
        primary=_remote_adapter(create_status=500),
        fallback=_LocalStub(),
    )
    events = await _drive(port)
    result = events[-1].result
    assert result is not None and result.status == AgentExecutionStatus.SUCCEEDED
    assert result.content == "你好"  # 本地兜底产出
    assert [e.delta for e in events if e.delta] == ["你", "好"]
