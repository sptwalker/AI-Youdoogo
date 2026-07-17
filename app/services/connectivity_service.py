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


async def _test_embedding() -> dict[str, Any]:
    """向量模型连通性：真实 embed 一小段文本，回向量维度。"""
    from app.knowledge.embedding import _api_key, embed_query

    if not _api_key():
        return {"target": "embedding", "status": "not_configured", "latency_ms": 0,
                "msg": "未配置向量模型密钥"}
    t0 = time.monotonic()
    try:
        vec = await embed_query("连通测试")
        return {"target": "embedding", "status": "ok", "latency_ms": _elapsed(t0),
                "msg": f"向量可达（{len(vec)} 维）"}
    except Exception as exc:  # noqa: BLE001 - 探针需吞异常报状态
        return {"target": "embedding", "status": "fail", "latency_ms": _elapsed(t0),
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
    from app.core import runtime_config

    # 读生效地址：UI 填的 sys_config 覆盖优先，回退 .env（与 ops_data 取数口径一致）
    base_url = str(runtime_config.effective("td_base_url", get_settings().td_base_url) or "")
    if not base_url:
        return {"target": "thinkingdata", "status": "not_configured", "latency_ms": 0,
                "msg": "未配置 TD 地址"}
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=5) as c:
            await c.get(base_url)  # 网络可达即算通（鉴权/取数靠「运营数据读取测试」）
        return {"target": "thinkingdata", "status": "ok", "latency_ms": _elapsed(t0),
                "msg": "网络可达"}
    except Exception as exc:  # noqa: BLE001
        return {"target": "thinkingdata", "status": "fail", "latency_ms": _elapsed(t0),
                "msg": str(exc)[:120]}


async def test_all() -> list[dict[str, Any]]:
    """依次测 LLM / 向量模型 / 飞书 / ThinkingData 连通性。"""
    return [
        await _test_llm(),
        await _test_embedding(),
        await _test_feishu(),
        await _test_thinkingdata(),
    ]
