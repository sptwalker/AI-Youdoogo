"""LLM-backed memory distillation adapter over the model gateway."""

from __future__ import annotations

import time

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.usage_budget.public import record_usage
from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
    MemoryDraft,
)
from app.contexts.foundations.knowledge.organizational_memory.domain.policies import (
    build_distillation_input,
)
from app.contexts.foundations.model_gateway.contracts.completion import (
    LlmCompletionPort,
    LlmCompletionRequest,
)

_DISTILL_SYSTEM = (
    "你是记忆整理助手。把一段对话记录提炼成结构化的长期记忆，供日后检索。"
    "严格按以下结构输出（无对应内容的小节写「无」）：\n"
    "## 摘要\n（2~4 句话概括这段对话谈了什么）\n"
    "## 关键事实与决定\n（逐条列出确定的事实、结论、达成的决定；无则写「无」）\n"
    "## 涉及实体\n（人名/项目/产品/部门/指标等专有名词，逗号分隔）\n"
    "## 用户偏好与习惯\n（对方表达的偏好、要求、工作习惯；无则写「无」）\n"
    "只输出上述结构化内容，不要寒暄，不要编造未出现的信息。"
)


class LlmMemoryDistillation:
    def __init__(self, session: AsyncSession, port: LlmCompletionPort) -> None:
        self._session = session
        self._port = port

    async def distill(self, command: DistillConversationCommand) -> MemoryDraft | None:
        started = time.monotonic()
        response = await self._port.invoke(
            LlmCompletionRequest(
                model_role="default",
                system_prompt=_DISTILL_SYSTEM,
                user_message=build_distillation_input(command.transcript),
                temperature=0.2,
            )
        )
        await record_usage(
            self._session,
            role="memory_distill",
            model=response.model or "default",
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            total_tokens=response.usage.total_tokens,
            duration_ms=int((time.monotonic() - started) * 1000),
            user_id=command.principal_id,
        )
        normalized = response.content.strip()
        if not normalized:
            return None
        return MemoryDraft(
            content=normalized,
            source_type=command.source_type,
            source_id=command.source_id,
        )
