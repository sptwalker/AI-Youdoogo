"""Public composition seam for LLM completion.

Phase 1 的唯一切换点：把 ``LocalLlmAdapter`` 换成 ``RemoteLlmAdapter`` 只需改此处，
所有消费方（agent 执行、知识问答、连通探测……）自动改道，无需逐个修改。
"""

from __future__ import annotations

from app.contexts.foundations.model_gateway.contracts.completion import LlmCompletionPort
from app.contexts.foundations.model_gateway.infrastructure.local_adapter import (
    LocalLlmAdapter,
)
from app.llm import get_llm_for_role
from app.llm.usage import extract_usage


def build_local_llm_completion_port() -> LlmCompletionPort:
    """Build the in-process LLM completion port backed by the local gateway."""
    return LocalLlmAdapter(llm_factory=get_llm_for_role, usage_extractor=extract_usage)
