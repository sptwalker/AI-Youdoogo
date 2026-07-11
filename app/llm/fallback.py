"""LLM 调用失败自动切换（failover）— 移植自 Bottleneck-Hunter llm_clients.fallback。

FallbackChatModel 包住一串候选模型 `[(llm, provider, model), ...]`：主模型调用失败时
自动换用备选重试，四条路径（sync/async × generate/stream）全部覆盖。

相对源实现的减法：
- 遥测落库 / ContextVar 提示排水已删除，usage 与切换提示统一走 logging；
- 熔断状态仍旁路写入 app.llm.health（进程内存态）。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator, Iterator
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from pydantic import ConfigDict

from app.llm.health import health
from app.llm.validate import validate_output

logger = logging.getLogger(__name__)


def classify_reason(exc: Exception) -> str:
    """把异常映射成面向用户的中文短语（也是 health 冷却时长的依据）。"""
    if isinstance(exc, asyncio.TimeoutError | TimeoutError):
        return "请求超时"
    msg = str(exc).lower()
    status = getattr(exc, "status_code", None) or getattr(exc, "http_status", None)
    _auth_markers = (
        "api key", "api_key", "unauthorized", "authentication", "invalid key", "permission",
    )
    if status in (401, 403) or any(k in msg for k in _auth_markers):
        return "认证失败(密钥无效)"
    _quota_markers = (
        "rate limit", "rate_limit", "too many requests", "quota", "余额", "insufficient",
    )
    if status == 429 or any(k in msg for k in _quota_markers):
        return "频率限制/额度不足"
    if isinstance(exc, ConnectionError | OSError) or any(
        k in msg for k in ("connection", "connect", "getaddrinfo", "network", "remotedisconnected")
    ):
        return "连接失败"
    if isinstance(exc, asyncio.CancelledError):
        return "调用被取消"
    if (
        (isinstance(status, int) and 500 <= status < 600)
        or "internal server" in msg
        or "bad gateway" in msg
        or "service unavailable" in msg
    ):
        return "服务端错误"
    if "timeout" in msg or "timed out" in msg:
        return "请求超时"
    return "调用异常"


def _validate(msg: Any) -> tuple[bool, str]:
    """输出格式校验。fail-silent：校验层异常绝不影响主链路（放行）。"""
    try:
        return validate_output(msg)
    except Exception:  # noqa: BLE001
        return True, ""


def _record_call(provider: str, model: str, ok: bool, t0: float, reason: str = "") -> None:
    """记一次候选调用：更新进程内熔断状态 + 用量日志（首版不入库）。"""
    elapsed_ms = (time.monotonic() - t0) * 1000
    try:
        if ok:
            health.record_success(provider)
        else:
            health.record_failure(provider, reason)
    except Exception:  # noqa: BLE001 - 熔断更新绝不影响主链路
        pass
    logger.info(
        "LLM调用 provider=%s model=%s 结果=%s 耗时=%.0fms%s",
        provider, model, "成功" if ok else "失败", elapsed_ms,
        f" 原因={reason}" if reason else "",
    )


class FallbackChatModel(BaseChatModel):
    """按顺序尝试候选 `[(llm, provider, model), ...]`，失败即换下一个并记日志。

    - 只有「换到备选并成功」才发出 warning；主模型直接成功不提示。
    - 全部失败 → 抛最后一个异常，保持上层既有 try/except 降级行为。
    - 末候选即便输出格式校验不佳也接受（不为格式问题整体失败）。
    - 流式路径已吐出部分 token 后失败无法安全重启，直接上抛。
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    candidates: list[tuple[BaseChatModel, str, str]]

    @property
    def _llm_type(self) -> str:
        return "fallback"

    def _notify(self, first_reason: str, win_provider: str, win_model: str) -> None:
        fp, fm = self.candidates[0][1], self.candidates[0][2]
        logger.warning(
            "模型自动替换：%s/%s 因%s调用失败，本次已替换为 %s/%s",
            fp, fm, first_reason, win_provider, win_model,
        )

    # ── async（主用路径）──────────────────────────────
    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_exc: Exception | None = None
        first_reason: str | None = None
        for i, (llm, provider, model) in enumerate(self.candidates):
            t0 = time.monotonic()
            try:
                msg = await llm.ainvoke(messages, stop=stop, **kwargs)
                vok, vreason = _validate(msg)
                accept = vok or i == len(self.candidates) - 1
                _record_call(provider, model, accept, t0, "" if accept else vreason)
                if accept:
                    if i > 0:
                        self._notify(first_reason or "调用异常", provider, model)
                    return ChatResult(generations=[ChatGeneration(message=msg)])
                last_exc = last_exc or ValueError(vreason)
                if i == 0:
                    first_reason = vreason
                logger.warning(
                    "候选模型 %s/%s 输出校验不合格(%s)，尝试下一候选", provider, model, vreason
                )
            except Exception as e:  # noqa: BLE001 - 逐候选降级
                last_exc = e
                reason = classify_reason(e)
                _record_call(provider, model, False, t0, reason)
                if i == 0:
                    first_reason = reason
                logger.warning("候选模型 %s/%s 调用失败(%s): %s", provider, model, reason, e)
        raise last_exc or RuntimeError("FallbackChatModel 无候选模型")

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        last_exc: Exception | None = None
        first_reason: str | None = None
        for i, (llm, provider, model) in enumerate(self.candidates):
            emitted = False
            t0 = time.monotonic()
            try:
                async for chunk in llm.astream(messages, stop=stop, **kwargs):
                    emitted = True
                    yield ChatGenerationChunk(message=chunk)
                _record_call(provider, model, True, t0)
                if i > 0:
                    self._notify(first_reason or "调用异常", provider, model)
                return
            except Exception as e:  # noqa: BLE001
                reason = classify_reason(e)
                _record_call(provider, model, False, t0, reason)
                if emitted:
                    raise  # 已吐出部分 token，无法安全重启，交由上层处理
                last_exc = e
                if i == 0:
                    first_reason = reason
                logger.warning("候选模型 %s/%s 流式失败(%s): %s", provider, model, reason, e)
        if last_exc:
            raise last_exc

    # ── sync（少数同步调用路径）──────────────────────
    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        last_exc: Exception | None = None
        first_reason: str | None = None
        for i, (llm, provider, model) in enumerate(self.candidates):
            t0 = time.monotonic()
            try:
                msg = llm.invoke(messages, stop=stop, **kwargs)
                vok, vreason = _validate(msg)
                accept = vok or i == len(self.candidates) - 1
                _record_call(provider, model, accept, t0, "" if accept else vreason)
                if accept:
                    if i > 0:
                        self._notify(first_reason or "调用异常", provider, model)
                    return ChatResult(generations=[ChatGeneration(message=msg)])
                last_exc = last_exc or ValueError(vreason)
                if i == 0:
                    first_reason = vreason
                logger.warning(
                    "候选模型 %s/%s 输出校验不合格(%s)，尝试下一候选", provider, model, vreason
                )
            except Exception as e:  # noqa: BLE001
                last_exc = e
                reason = classify_reason(e)
                _record_call(provider, model, False, t0, reason)
                if i == 0:
                    first_reason = reason
                logger.warning("候选模型 %s/%s 调用失败(%s): %s", provider, model, reason, e)
        raise last_exc or RuntimeError("FallbackChatModel 无候选模型")

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        last_exc: Exception | None = None
        first_reason: str | None = None
        for i, (llm, provider, model) in enumerate(self.candidates):
            emitted = False
            t0 = time.monotonic()
            try:
                for chunk in llm.stream(messages, stop=stop, **kwargs):
                    emitted = True
                    yield ChatGenerationChunk(message=chunk)
                _record_call(provider, model, True, t0)
                if i > 0:
                    self._notify(first_reason or "调用异常", provider, model)
                return
            except Exception as e:  # noqa: BLE001
                reason = classify_reason(e)
                _record_call(provider, model, False, t0, reason)
                if emitted:
                    raise
                last_exc = e
                if i == 0:
                    first_reason = reason
                logger.warning("候选模型 %s/%s 流式失败(%s): %s", provider, model, reason, e)
        if last_exc:
            raise last_exc
