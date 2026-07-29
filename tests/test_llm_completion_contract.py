"""LLM 完成端口消费者契约（D1 / docs/21 §D「建立消费者契约测试流水线」）。

一份**契约**（消费方依赖的不变量）× 参数化跑遍**每个** `LlmCompletionPort` 实现 = 契约流水线。
pytest 参数化即流水线，无需自造 runner。今天注册两个走真实不同代码路径的实现：
`LocalLlmAdapter`（真归一化路径 + stub transport）与 `ReplayLlmAdapter`（D4 录制样本），证明契约
非自证同义反复。Phase 1 `RemoteLlmAdapter` 上线只需在 CASES 追加一个 case，即被同一契约门禁。

# ponytail: 只为首个将远程化的端口（LLM 完成）建契约；其余端口（Knowledge/Expert）走远程时
# 照此模式各加一份契约文件即可，现在建 = 无远程实现的空壳（YAGNI）。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
from langchain_core.messages import AIMessage, AIMessageChunk

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionPort,
    LlmCompletionRequest,
)
from app.contexts.foundations.model_gateway.infrastructure.local_adapter import LocalLlmAdapter
from app.contexts.foundations.model_gateway.infrastructure.remote_adapter import RemoteLlmAdapter
from scripts.llm_replay import KIND_STREAMING, ReplayLlmAdapter, load_samples, stream_is_consistent


async def assert_llm_completion_contract(
    adapter: LlmCompletionPort,
    *,
    invoke_request: LlmCompletionRequest,
    stream_request: LlmCompletionRequest,
) -> None:
    """任何 LlmCompletionPort 实现都必须满足的消费方契约。"""
    resp = await adapter.invoke(invoke_request)
    assert isinstance(resp.content, str) and resp.content  # 非空文本产出
    assert resp.model is None or isinstance(resp.model, str)
    for value in (resp.usage.prompt_tokens, resp.usage.completion_tokens, resp.usage.total_tokens):
        assert isinstance(value, int) and value >= 0  # 用量非负整数

    chunks = [chunk async for chunk in adapter.stream(stream_request)]
    assert stream_is_consistent(chunks)  # 逐步 accumulated = 前缀 + delta
    if chunks:
        assert chunks[-1].accumulated_content == "".join(c.delta for c in chunks)
        assert all(c.usage.total_tokens >= 0 for c in chunks)


class _StubLlm:
    """本地适配器的 stub transport：ainvoke 回预置 reply，astream 吐预置块。"""

    def __init__(self, reply: AIMessage, stream: list[AIMessageChunk]) -> None:
        self._reply = reply
        self._stream = stream

    async def ainvoke(self, _messages: list[Any]) -> AIMessage:
        return self._reply

    async def astream(self, _messages: list[Any]) -> AsyncIterator[AIMessageChunk]:
        for chunk in self._stream:
            yield chunk


def _local_case() -> tuple[LlmCompletionPort, LlmCompletionRequest, LlmCompletionRequest]:
    stub = _StubLlm(
        reply=AIMessage(content="本地产出", response_metadata={"model_name": "m"}),
        stream=[AIMessageChunk(content="本"), AIMessageChunk(content="地")],
    )
    adapter = LocalLlmAdapter(
        llm_factory=lambda _role, *, temperature: stub,
        usage_extractor=lambda _reply: (1, 2, 3),
    )
    request = LlmCompletionRequest(model_role="daily", system_prompt="s", user_message="u")
    return adapter, request, request


def _replay_case() -> tuple[LlmCompletionPort, LlmCompletionRequest, LlmCompletionRequest]:
    samples = load_samples()
    non_streaming = next(s for s in samples if s.response is not None)
    streaming = next(s for s in samples if s.kind == KIND_STREAMING)
    return ReplayLlmAdapter(samples), non_streaming.request, streaming.request


def _remote_case() -> tuple[LlmCompletionPort, LlmCompletionRequest, LlmCompletionRequest]:
    """RemoteLlmAdapter + MockTransport 回放自洽 chat/SSE：证明远程实现满足同一契约。"""

    def handle(request: httpx.Request) -> httpx.Response:
        if json.loads(request.content).get("stream"):
            body = (
                'data: {"delta": "远", "accumulated_content": "远"}\n\n'
                'data: {"delta": "程", "accumulated_content": "远程"}\n\n'
                "data: [DONE]\n\n"
            )
            return httpx.Response(200, content=body.encode("utf-8"))
        return httpx.Response(
            200, json={"content": "远程产出", "model": "m", "usage": {"total_tokens": 3}}
        )

    adapter = RemoteLlmAdapter(
        base_url="http://gateway.test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
        token_minter=lambda: "stub-token",
    )
    request = LlmCompletionRequest(model_role="daily", system_prompt="s", user_message="u")
    return adapter, request, request


_Case = tuple[LlmCompletionPort, LlmCompletionRequest, LlmCompletionRequest]
CASES: dict[str, Callable[[], _Case]] = {
    "local": _local_case,
    "replay": _replay_case,
    "remote": _remote_case,
}


@pytest.mark.parametrize("case_name", list(CASES))
async def test_llm_completion_port_honors_contract(case_name: str) -> None:
    adapter, invoke_request, stream_request = CASES[case_name]()
    await assert_llm_completion_contract(
        adapter, invoke_request=invoke_request, stream_request=stream_request
    )
