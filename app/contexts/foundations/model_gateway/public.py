"""Public composition seam for LLM completion.

Phase 1 的唯一切换点：``build_llm_completion_port()`` 按配置在 Local / Remote 间二选一，
所有消费方（agent 执行、知识问答、连通探测……）自动改道，无需逐个修改（Branch-by-Abstraction）。
"""

from __future__ import annotations

import secrets

from app.contexts.foundations.governance.usage_budget.public import extract_usage
from app.contexts.foundations.model_gateway.contracts.completion import LlmCompletionPort
from app.contexts.foundations.model_gateway.infrastructure.fallback_adapter import (
    FallbackCompletionPort,
)
from app.contexts.foundations.model_gateway.infrastructure.local_adapter import (
    LocalLlmAdapter,
)
from app.contexts.foundations.model_gateway.infrastructure.remote_adapter import (
    RemoteLlmAdapter,
)
from app.core.config import get_settings
from app.llm import get_llm_for_role


def build_local_llm_completion_port() -> LlmCompletionPort:
    """Build the in-process LLM completion port backed by the local gateway."""
    return LocalLlmAdapter(llm_factory=get_llm_for_role, usage_extractor=extract_usage)


def build_remote_llm_completion_port() -> LlmCompletionPort:
    """Build the LLM completion port that speaks to the remote model gateway over HTTP."""
    return RemoteLlmAdapter(base_url=get_settings().llm_gateway_url)


def _route_remote(percent: int) -> bool:
    """按调用抽样决定本次是否走远程网关（docs/21 步骤5 百分比 canary）。

    percent=0 恒 local（生产默认，安全）；100 恒 remote；0<p<100 按 p% 概率抽样。
    用 secrets.randbelow 均匀抽样（非密码学诉求，仅取其无种子依赖）。
    """
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    return secrets.randbelow(100) < percent


def build_llm_completion_port() -> LlmCompletionPort:
    """选择器：mode=remote 且配了网关地址时，按 canary 百分比抽样路由 Remote / Local。

    默认 local（percent=0 或 mode=local，无服务时安全）；0<percent<100 为灰度期，
    单次调用按概率落到 Remote 或 Local；percent=100 等价整体切换。回滚=percent 归 0。

    路线 A：命中远程时不裸返 Remote，而是包一层 remote→local 兜底（本地为永久安全网），
    远程失败静默落本地，把 canary 风险压到 ~0；本地端口永不删。
    ponytail: 按 use_case / knowledge_base 维度的定向灰度待有在线流量证据时再加。
    """
    settings = get_settings()
    if (
        settings.llm_completion_mode == "remote"
        and settings.llm_gateway_url
        and _route_remote(settings.llm_gateway_canary_percent)
    ):
        return FallbackCompletionPort(
            primary=build_remote_llm_completion_port(),
            fallback=build_local_llm_completion_port(),
        )
    return build_local_llm_completion_port()

