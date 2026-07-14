"""AI 卡片连通性测试（仿 Bottleneck-Hunter model_tester，做减法：只测连通）。

test_card(base_url, api_key, model)：向该 OpenAI 兼容端点发一条最小请求，限时返回
{status: ok/fail, latency_ms, msg}。不落库、不走 factory 注册表（拿裸参数直连），
供 ai_provider_service 在新增/编辑/一键检测时调用。
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from langchain_core.messages import HumanMessage
from pydantic import SecretStr

_TIMEOUT_S = 20


async def test_card(
    base_url: str, api_key: str, model: str, timeout: int = _TIMEOUT_S
) -> dict[str, Any]:
    """测一张卡片的连通性。任何失败都吞成 status=fail（探针语义，不抛）。"""
    if not base_url or not model:
        return {"status": "fail", "latency_ms": 0, "msg": "缺少地址或模型名"}
    from langchain_openai import ChatOpenAI

    t0 = time.monotonic()
    try:
        llm = ChatOpenAI(
            model=model,
            api_key=SecretStr(api_key or "not-needed"),
            base_url=base_url,
            temperature=0,
            timeout=timeout,
            max_retries=0,
        )
        resp = await asyncio.wait_for(
            llm.ainvoke([HumanMessage(content="hi")]), timeout=timeout
        )
        latency = int((time.monotonic() - t0) * 1000)
        content = resp.content if isinstance(resp.content, str) else str(resp.content)
        if not content.strip():
            return {"status": "fail", "latency_ms": latency, "msg": "端点返回空内容"}
        return {"status": "ok", "latency_ms": latency, "msg": "连通正常"}
    except TimeoutError:
        return {"status": "fail", "latency_ms": int((time.monotonic() - t0) * 1000),
                "msg": f"请求超时（{timeout}s）"}
    except Exception as exc:  # noqa: BLE001 - 探针需吞一切异常报状态
        return {"status": "fail", "latency_ms": int((time.monotonic() - t0) * 1000),
                "msg": str(exc)[:200]}
