"""Public composition seam for LLM completion.

Phase 1 的唯一切换点：``build_llm_completion_port()`` 按配置在 Local / Remote 间二选一，
所有消费方（agent 执行、知识问答、连通探测……）自动改道，无需逐个修改（Branch-by-Abstraction）。
"""

from __future__ import annotations

from app.contexts.foundations.governance.usage_budget.public import extract_usage
from app.contexts.foundations.model_gateway.contracts.completion import LlmCompletionPort
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


def build_llm_completion_port() -> LlmCompletionPort:
    """选择器：mode=remote 且配了网关地址 → 远程，否则本地（默认 local，无服务时安全）。

    ponytail: 目前是整体开关（一个配置翻转全量切换）；按 use_case / knowledge_base /
    百分比灰度路由待网关真上线、有在线流量证据时再加（docs/21 Phase 1 步骤 5）。
    """
    settings = get_settings()
    if settings.llm_completion_mode == "remote" and settings.llm_gateway_url:
        return build_remote_llm_completion_port()
    return build_local_llm_completion_port()

