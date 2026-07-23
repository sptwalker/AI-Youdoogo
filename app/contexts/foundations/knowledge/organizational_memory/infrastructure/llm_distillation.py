"""LLM-backed memory distillation adapter."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
    MemoryDraft,
)
from app.contexts.foundations.knowledge.organizational_memory.domain.policies import (
    build_distillation_input,
)
from app.llm.usage import extract_usage, record_usage

_DISTILL_SYSTEM = (
    "你是记忆整理助手。把一段对话记录提炼成结构化的长期记忆，供日后检索。"
    "严格按以下结构输出（无对应内容的小节写「无」）：\n"
    "## 摘要\n（2~4 句话概括这段对话谈了什么）\n"
    "## 关键事实与决定\n（逐条列出确定的事实、结论、达成的决定；无则写「无」）\n"
    "## 涉及实体\n（人名/项目/产品/部门/指标等专有名词，逗号分隔）\n"
    "## 用户偏好与习惯\n（对方表达的偏好、要求、工作习惯；无则写「无」）\n"
    "只输出上述结构化内容，不要寒暄，不要编造未出现的信息。"
)


LlmFactory = Callable[..., Any]


class LlmMemoryDistillation:
    def __init__(self, session: AsyncSession, llm_factory: LlmFactory) -> None:
        self._session = session
        self._llm_factory = llm_factory

    async def distill(self, command: DistillConversationCommand) -> MemoryDraft | None:
        llm = self._llm_factory("default", temperature=0.2)
        started = time.monotonic()
        reply = await llm.ainvoke(
            [
                SystemMessage(content=_DISTILL_SYSTEM),
                HumanMessage(content=build_distillation_input(command.transcript)),
            ]
        )
        prompt_tokens, completion_tokens, total_tokens = extract_usage(reply)
        await record_usage(
            self._session,
            role="memory_distill",
            model=str(reply.response_metadata.get("model_name") or "default"),
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            duration_ms=int((time.monotonic() - started) * 1000),
            user_id=command.principal_id,
        )
        content = reply.content if isinstance(reply.content, str) else str(reply.content)
        normalized = content.strip()
        if not normalized:
            return None
        return MemoryDraft(
            content=normalized,
            source_type=command.source_type,
            source_id=command.source_id,
        )
