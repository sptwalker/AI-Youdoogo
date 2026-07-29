"""LocalLlmAdapter 归一化特征化测试（D2 / docs/21 §D「补现有关键链路 Characterization Test」）。

钉住本地适配器把 langchain 消息 → 纯 `LlmCompletion*` 契约的**当前可观测行为**：Phase 1 的
`RemoteLlmAdapter` 实现同一端口时，必须逐字复现这些性质（配 D4 回放样本即得离线 parity）。
用 stub llm_factory（返回预置 AIMessage/AIMessageChunk），不发真实请求、无 DB。

被钉住的行为：
- model 回退：response_metadata 无 model_name 时回退到 request.model_role；
- 空 system_prompt 的 wire 行为：只发 [HumanMessage]，不前置 SystemMessage；
- 流式累积：delta=本块文本，accumulated=累计文本，非 AIMessageChunk 被跳过；
- usage 经 usage_extractor(reply) 透传进 TokenUsage。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, SystemMessage

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
    TokenUsage,
)
from app.contexts.foundations.model_gateway.infrastructure.local_adapter import LocalLlmAdapter


class _FakeLlm:
    """记录收到的 prompt 消息；ainvoke 回预置 reply，astream 吐预置块序列。"""

    def __init__(self, *, reply: AIMessage | None = None, stream: list[Any] | None = None) -> None:
        self._reply = reply
        self._stream = stream or []
        self.seen_messages: list[Any] | None = None
        self.seen_role: str | None = None
        self.seen_temperature: float | None = None

    async def ainvoke(self, messages: list[Any]) -> AIMessage:
        self.seen_messages = messages
        assert self._reply is not None
        return self._reply

    async def astream(self, messages: list[Any]) -> AsyncIterator[Any]:
        self.seen_messages = messages
        for chunk in self._stream:
            yield chunk


def _adapter(fake: _FakeLlm) -> LocalLlmAdapter:
    def factory(model_role: str, *, temperature: float) -> _FakeLlm:
        fake.seen_role = model_role
        fake.seen_temperature = temperature
        return fake

    return LocalLlmAdapter(llm_factory=factory, usage_extractor=lambda _reply: (11, 22, 33))


async def test_invoke_normalizes_content_model_and_usage() -> None:
    fake = _FakeLlm(
        reply=AIMessage(
            content="盒子A5 是智能机顶盒。", response_metadata={"model_name": "deepseek-chat"}
        )
    )
    resp = await _adapter(fake).invoke(
        LlmCompletionRequest(model_role="daily", system_prompt="你是助手。", user_message="介绍A5")
    )
    assert resp.content == "盒子A5 是智能机顶盒。"
    assert resp.model == "deepseek-chat"
    assert resp.usage == TokenUsage(11, 22, 33)  # usage_extractor 透传
    assert fake.seen_role == "daily" and fake.seen_temperature == 0.3


async def test_invoke_falls_back_to_model_role_when_metadata_missing() -> None:
    fake = _FakeLlm(reply=AIMessage(content="x", response_metadata={}))
    resp = await _adapter(fake).invoke(
        LlmCompletionRequest(model_role="reasoning", system_prompt="s", user_message="u")
    )
    assert resp.model == "reasoning"  # 无 model_name → 回退档位名


async def test_empty_system_prompt_omits_system_message() -> None:
    fake = _FakeLlm(reply=AIMessage(content="x", response_metadata={}))
    await _adapter(fake).invoke(
        LlmCompletionRequest(model_role="daily", system_prompt="   ", user_message="只有用户话")
    )
    assert fake.seen_messages is not None
    assert [type(m) for m in fake.seen_messages] == [HumanMessage]  # 空白 system 不前置

    fake2 = _FakeLlm(reply=AIMessage(content="x", response_metadata={}))
    await _adapter(fake2).invoke(
        LlmCompletionRequest(model_role="daily", system_prompt="你是助手。", user_message="q")
    )
    assert [type(m) for m in fake2.seen_messages or []] == [SystemMessage, HumanMessage]


async def test_stream_accumulates_and_skips_non_chunks() -> None:
    fake = _FakeLlm(
        stream=[
            AIMessageChunk(content="盒子"),
            AIMessage(content="忽略"),  # 非 AIMessageChunk → 应跳过，不进 delta/accumulated
            AIMessageChunk(content="A5"),
        ]
    )
    chunks = [
        c
        async for c in _adapter(fake).stream(
            LlmCompletionRequest(model_role="daily", system_prompt="", user_message="分辨率？")
        )
    ]
    assert [c.delta for c in chunks] == ["盒子", "A5"]  # 非块被跳过
    assert [c.accumulated_content for c in chunks] == ["盒子", "盒子A5"]  # 逐步累积
    assert chunks[-1].model == "daily"  # 块无 model_name → 回退档位名
    assert chunks[-1].usage == TokenUsage(11, 22, 33)
