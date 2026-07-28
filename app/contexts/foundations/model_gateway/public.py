"""Public composition seam for LLM completion.

Phase 1 的唯一切换点：把 ``LocalLlmAdapter`` 换成 ``RemoteLlmAdapter`` 只需改此处，
所有消费方（agent 执行、知识问答、连通探测……）自动改道，无需逐个修改。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from app.contexts.foundations.governance.usage_budget.public import extract_usage
from app.contexts.foundations.model_gateway.contracts.completion import LlmCompletionPort
from app.contexts.foundations.model_gateway.infrastructure.local_adapter import (
    LocalLlmAdapter,
)
from app.llm import get_llm_for_role


def build_local_llm_completion_port(
    *,
    llm_factory: Callable[..., Any] | None = None,
) -> LlmCompletionPort:
    """Build the in-process LLM completion port backed by the local gateway."""
    return LocalLlmAdapter(
        llm_factory=llm_factory or get_llm_for_role,
        usage_extractor=extract_usage,
    )
