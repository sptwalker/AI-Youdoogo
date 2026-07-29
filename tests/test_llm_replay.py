"""LLM 回放样本/适配器测试（无 DB、无真 LLM）：样本自洽 + 回放经端口产出录制 DTO。"""

from __future__ import annotations

import pytest

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
    LlmCompletionStreamChunk,
    TokenUsage,
)
from scripts.llm_replay import (
    KIND_NON_STREAMING,
    KIND_STREAMING,
    ReplayLlmAdapter,
    load_samples,
    stream_is_consistent,
)


def test_stream_is_consistent_detects_broken_recording() -> None:
    good = [
        LlmCompletionStreamChunk(delta="a", accumulated_content="a"),
        LlmCompletionStreamChunk(delta="b", accumulated_content="ab"),
    ]
    assert stream_is_consistent(good) is True
    assert stream_is_consistent([]) is True  # 空流自洽
    bad = [
        LlmCompletionStreamChunk(delta="a", accumulated_content="a"),
        LlmCompletionStreamChunk(delta="b", accumulated_content="aXb"),  # 拼接不符
    ]
    assert stream_is_consistent(bad) is False


def test_bundled_samples_load_and_cover_both_kinds() -> None:
    samples = load_samples()
    kinds = {s.kind for s in samples}
    assert KIND_NON_STREAMING in kinds and KIND_STREAMING in kinds  # 两档样本齐备


async def test_replay_invoke_returns_recorded_response() -> None:
    adapter = ReplayLlmAdapter(load_samples())
    request = LlmCompletionRequest(
        model_role="daily",
        system_prompt="你是创想悦动的运营助手，回答简洁准确。",
        user_message="一句话介绍智能盒子A5。",
    )
    resp = await adapter.invoke(request)
    assert "盒子A5" in resp.content
    assert resp.model == "deepseek-chat"
    assert resp.usage == TokenUsage(42, 24, 66)


async def test_replay_stream_yields_recorded_chunks() -> None:
    adapter = ReplayLlmAdapter(load_samples())
    request = LlmCompletionRequest(
        model_role="daily",
        system_prompt="你是创想悦动的运营助手，回答简洁准确。",
        user_message="盒子A5 支持哪些分辨率？",
    )
    chunks = [chunk async for chunk in adapter.stream(request)]
    assert len(chunks) == 4
    assert stream_is_consistent(chunks)
    assert chunks[-1].accumulated_content == "盒子A5支持 1080P 与 4K 输出。"


async def test_replay_misses_raise_not_silent() -> None:
    adapter = ReplayLlmAdapter(load_samples())
    with pytest.raises(LookupError):
        await adapter.invoke(LlmCompletionRequest("daily", "x", "无此样本"))
