"""model_gateway 接缝自证：answer() 与连通探测确实经 LlmCompletionPort 完成（不发真实请求）。

覆盖 ADR 0001 的两处收编，用 fake 端口记录调用，验证「一处切换即改道」的前提成立。
"""

from __future__ import annotations

import uuid

import pytest

from app.contexts.foundations.governance.system_configuration.connectivity.infrastructure import (
    adapters as connectivity_adapters,
)
from app.contexts.foundations.knowledge.knowledge_retrieval.infrastructure import (
    sqlalchemy_retrieval as retrieval,
)
from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
    LlmCompletionResponse,
    TokenUsage,
)


class _FakePort:
    """记录收到的请求；invoke 返回固定回复。"""

    def __init__(self) -> None:
        self.requests: list[LlmCompletionRequest] = []

    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        self.requests.append(request)
        return LlmCompletionResponse(
            content="来自 fake 端口的回复", model="fake-model", usage=TokenUsage(1, 2, 3)
        )

    def stream(self, request: LlmCompletionRequest):  # pragma: no cover - 未用到
        raise NotImplementedError


@pytest.mark.asyncio
async def test_answer_routes_through_injected_completion_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """answer() 走注入端口：命中一条资料 → 端口收到请求，回复/来源如实透传。"""
    fid = uuid.uuid4()
    hit = retrieval.Hit(
        file_id=fid, file_name="doc.md", chunk_index=0, chunk_text="资料内容", distance=0.1
    )

    async def _fake_search(*args: object, **kwargs: object) -> list[retrieval.Hit]:
        return [hit]

    async def _fake_record_usage(*args: object, **kwargs: object) -> None:
        return None

    monkeypatch.setattr(retrieval, "search", _fake_search)
    monkeypatch.setattr(retrieval, "record_usage", _fake_record_usage)
    port = _FakePort()

    result = await retrieval.answer(object(), "问题?", port=port)  # type: ignore[arg-type]

    assert len(port.requests) == 1
    assert port.requests[0].model_role == "default"
    assert result["answer"] == "来自 fake 端口的回复"
    assert result["sources"][0]["file_id"] == str(fid)


@pytest.mark.asyncio
async def test_connectivity_probe_routes_through_completion_port(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """探测成功仅需端口不抛异常；确认它经 build_local_llm_completion_port 拿端口。"""
    port = _FakePort()
    monkeypatch.setattr(
        connectivity_adapters, "build_local_llm_completion_port", lambda: port
    )

    result = await connectivity_adapters.LLMConnectivityProbe().probe()

    assert result.status == "ok"
    assert port.requests and port.requests[0].user_message == "ping"
