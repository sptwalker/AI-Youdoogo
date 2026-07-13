"""数据接口/外部依赖连通性测试（F5c，仅 admin 手动触发）。

真探针：LLM 最小 ping / 飞书 tenant token / ThinkingData 网络可达。
只回 ok/fail/not_configured + 延迟 + 简短消息，绝不回显任何密钥。
# ponytail: 外部真实调用，难做有意义单测；靠真机手动验收。
"""

from __future__ import annotations

import time
from typing import Any

import httpx
from langchain_core.messages import HumanMessage

from app.core.config import get_settings
from app.integrations.feishu.client import FeishuClient
from app.llm import get_llm_for_role


def _elapsed(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


async def _test_llm() -> dict[str, Any]:
    t0 = time.monotonic()
    try:
        llm = get_llm_for_role("default", temperature=0)
        await llm.ainvoke([HumanMessage(content="ping")])
        return {"target": "llm", "status": "ok", "latency_ms": _elapsed(t0), "msg": "模型可达"}
    except Exception as exc:  # noqa: BLE001 - 探针需吞异常报状态
        return {"target": "llm", "status": "fail", "latency_ms": _elapsed(t0),
                "msg": str(exc)[:120]}


async def _test_feishu() -> dict[str, Any]:
    s = get_settings()
    if not s.feishu_app_id or not s.feishu_app_secret:
        return {"target": "feishu", "status": "not_configured", "latency_ms": 0,
                "msg": "未配置 app_id/secret"}
    t0 = time.monotonic()
    try:
        await FeishuClient().get_tenant_access_token()
        return {"target": "feishu", "status": "ok", "latency_ms": _elapsed(t0), "msg": "鉴权通过"}
    except Exception as exc:  # noqa: BLE001
        return {"target": "feishu", "status": "fail", "latency_ms": _elapsed(t0),
                "msg": str(exc)[:120]}


async def _test_thinkingdata() -> dict[str, Any]:
    s = get_settings()
    if not s.td_base_url:
        return {"target": "thinkingdata", "status": "not_configured", "latency_ms": 0,
                "msg": "未配置 TD_BASE_URL"}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.get(s.td_base_url)  # 网络可达即算通（鉴权靠真实查询）
        return {"target": "thinkingdata", "status": "ok", "latency_ms": _elapsed(t0),
                "msg": "网络可达"}
    except Exception as exc:  # noqa: BLE001
        return {"target": "thinkingdata", "status": "fail", "latency_ms": _elapsed(t0),
                "msg": str(exc)[:120]}


async def test_all() -> list[dict[str, Any]]:
    """依次测 LLM / 飞书 / ThinkingData 连通性。"""
    return [await _test_llm(), await _test_feishu(), await _test_thinkingdata()]
