"""LLM 回放样本 + 回放适配器（D4 / docs/21 §D「准备 LLM 流式/非流式回放样本」）。

录制的样本按 **正典完成契约**（`model_gateway.contracts.completion` 的纯 DTO）落 JSON：
Phase 1 `RemoteLlmAdapter` 上线后，用同一 request 打真适配器、与录制样本比对即得**离线 parity**；
消费方 use_case 也能注入 `ReplayLlmAdapter` 做**不打真 LLM** 的离线测试。样本即契约固化物。

样本格式（scripts/llm_replay_samples/*.json）：
  非流式 {"kind":"non_streaming","request":{...},"response":{content,model,usage:{...}}}
  流式   {"kind":"streaming","request":{...},"chunks":[{delta,accumulated_content,model,usage},...]}

`stream_is_consistent` 是纯不变量（无 DB/无 LLM）：录制的流每步 accumulated = 前缀 + delta，
末步 accumulated == 各 delta 拼接——录制样本自洽的门槛，也是任何真适配器流必须满足的性质。
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
    LlmCompletionResponse,
    LlmCompletionStreamChunk,
    TokenUsage,
)

SAMPLES_DIR = Path(__file__).with_name("llm_replay_samples")

KIND_NON_STREAMING = "non_streaming"
KIND_STREAMING = "streaming"


@dataclass(frozen=True)
class ReplaySample:
    """一条录制样本：request + 非流式 response 或流式 chunks（按 kind 二选一）。"""

    kind: str
    request: LlmCompletionRequest
    response: LlmCompletionResponse | None = None
    chunks: tuple[LlmCompletionStreamChunk, ...] = ()


def _usage(raw: dict[str, object] | None) -> TokenUsage:
    raw = raw or {}
    return TokenUsage(
        int(raw.get("prompt_tokens", 0) or 0),
        int(raw.get("completion_tokens", 0) or 0),
        int(raw.get("total_tokens", 0) or 0),
    )


def _request(raw: dict[str, object]) -> LlmCompletionRequest:
    return LlmCompletionRequest(
        model_role=str(raw["model_role"]),
        system_prompt=str(raw.get("system_prompt", "")),
        user_message=str(raw["user_message"]),
        temperature=float(raw.get("temperature", 0.3)),  # type: ignore[arg-type]
    )


def load_sample(path: Path) -> ReplaySample:
    """载入并校验一条样本 JSON。kind 非法/字段缺失/流式不自洽 → ValueError。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    kind = raw.get("kind")
    request = _request(raw["request"])
    if kind == KIND_NON_STREAMING:
        resp = raw["response"]
        return ReplaySample(
            kind,
            request,
            response=LlmCompletionResponse(
                content=str(resp["content"]),
                model=resp.get("model"),
                usage=_usage(resp.get("usage")),
            ),
        )
    if kind == KIND_STREAMING:
        chunks = tuple(
            LlmCompletionStreamChunk(
                delta=str(c["delta"]),
                accumulated_content=str(c["accumulated_content"]),
                model=c.get("model"),
                usage=_usage(c.get("usage")),
            )
            for c in raw["chunks"]
        )
        if not stream_is_consistent(chunks):
            raise ValueError(f"{path.name}: 流式样本不自洽（accumulated 与 delta 拼接不符）")
        return ReplaySample(kind, request, chunks=chunks)
    raise ValueError(f"{path.name}: 未知 kind {kind!r}（须 non_streaming/streaming）")


def load_samples(directory: Path = SAMPLES_DIR) -> list[ReplaySample]:
    """载入目录下全部样本；空目录返回空表（首版无录制时不报错）。"""
    return [load_sample(p) for p in sorted(directory.glob("*.json"))]


def stream_is_consistent(chunks: Sequence[LlmCompletionStreamChunk]) -> bool:
    """录制流自洽：逐步 accumulated == 上一 accumulated + 本步 delta；空流视作自洽。"""
    acc = ""
    for chunk in chunks:
        acc += chunk.delta
        if chunk.accumulated_content != acc:
            return False
    return True


def _key(request: LlmCompletionRequest) -> tuple[str, str, str]:
    return (request.model_role, request.system_prompt, request.user_message)


class ReplayLlmAdapter:
    """`LlmCompletionPort` 的离线实现：按 request 命中录制样本回放，不打真 LLM。

    命中不到样本直接抛错（信任边界：不静默返回空，否则测试会误绿）。
    """

    def __init__(self, samples: Iterable[ReplaySample]) -> None:
        self._by_key: dict[tuple[str, str, str], ReplaySample] = {
            _key(s.request): s for s in samples
        }

    def _sample(self, request: LlmCompletionRequest) -> ReplaySample:
        sample = self._by_key.get(_key(request))
        if sample is None:
            raise LookupError(f"无匹配回放样本：model_role={request.model_role!r}")
        return sample

    async def invoke(self, request: LlmCompletionRequest) -> LlmCompletionResponse:
        sample = self._sample(request)
        if sample.response is None:
            raise LookupError("命中的是流式样本，invoke 需要 non_streaming 样本")
        return sample.response

    def stream(
        self, request: LlmCompletionRequest
    ) -> AsyncIterator[LlmCompletionStreamChunk]:
        sample = self._sample(request)

        async def _iterate() -> AsyncIterator[LlmCompletionStreamChunk]:
            if sample.kind != KIND_STREAMING:
                raise LookupError("命中的是非流式样本，stream 需要 streaming 样本")
            for chunk in sample.chunks:
                yield chunk

        return _iterate()
