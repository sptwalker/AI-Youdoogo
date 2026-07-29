"""Current LLM, embedding, Feishu, and ThinkingData connectivity probes."""

from __future__ import annotations

import time

import httpx

from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionRequest,
)
from app.contexts.foundations.model_gateway.public import build_llm_completion_port
from app.core import runtime_config
from app.core.config import get_settings
from app.integrations.feishu.client import FeishuClient
from app.knowledge.embedding import _api_key, embed_query

from ..contracts import ConnectivityProbeResult


def _elapsed(started_at: float) -> int:
    return int((time.monotonic() - started_at) * 1000)


class LLMConnectivityProbe:
    async def probe(self) -> ConnectivityProbeResult:
        started_at = time.monotonic()
        try:
            await build_llm_completion_port().invoke(
                LlmCompletionRequest(
                    model_role="default",
                    system_prompt="",
                    user_message="ping",
                    temperature=0,
                )
            )
            return ConnectivityProbeResult("llm", "ok", _elapsed(started_at), "模型可达")
        except Exception as exc:  # noqa: BLE001 - probes report rather than fail
            return ConnectivityProbeResult(
                "llm", "fail", _elapsed(started_at), str(exc)[:120]
            )


class EmbeddingConnectivityProbe:
    async def probe(self) -> ConnectivityProbeResult:
        if not _api_key():
            return ConnectivityProbeResult(
                "embedding", "not_configured", 0, "未配置向量模型密钥"
            )
        started_at = time.monotonic()
        try:
            vector = await embed_query("连通测试")
            return ConnectivityProbeResult(
                "embedding",
                "ok",
                _elapsed(started_at),
                f"向量可达（{len(vector)} 维）",
            )
        except Exception as exc:  # noqa: BLE001 - probes report rather than fail
            return ConnectivityProbeResult(
                "embedding", "fail", _elapsed(started_at), str(exc)[:120]
            )


class FeishuConnectivityProbe:
    async def probe(self) -> ConnectivityProbeResult:
        settings = get_settings()
        if not settings.feishu_app_id or not settings.feishu_app_secret:
            return ConnectivityProbeResult(
                "feishu", "not_configured", 0, "未配置 app_id/secret"
            )
        started_at = time.monotonic()
        try:
            await FeishuClient().get_tenant_access_token()
            return ConnectivityProbeResult(
                "feishu", "ok", _elapsed(started_at), "鉴权通过"
            )
        except Exception as exc:  # noqa: BLE001 - probes report rather than fail
            return ConnectivityProbeResult(
                "feishu", "fail", _elapsed(started_at), str(exc)[:120]
            )


class ThinkingDataConnectivityProbe:
    async def probe(self) -> ConnectivityProbeResult:
        base_url = str(
            runtime_config.effective("td_base_url", get_settings().td_base_url) or ""
        )
        if not base_url:
            return ConnectivityProbeResult(
                "thinkingdata", "not_configured", 0, "未配置 TD 地址"
            )
        started_at = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                await client.get(base_url)
            return ConnectivityProbeResult(
                "thinkingdata", "ok", _elapsed(started_at), "网络可达"
            )
        except Exception as exc:  # noqa: BLE001 - probes report rather than fail
            return ConnectivityProbeResult(
                "thinkingdata", "fail", _elapsed(started_at), str(exc)[:120]
            )
