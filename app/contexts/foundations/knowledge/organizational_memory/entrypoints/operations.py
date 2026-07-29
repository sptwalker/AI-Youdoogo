"""Request-scoped Organizational Memory operations."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.organizational_memory.application.use_cases import (
    OrganizationalMemory,
)
from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
    MemoryDraft,
)
from app.contexts.foundations.knowledge.organizational_memory.infrastructure import (
    llm_distillation,
)
from app.contexts.foundations.model_gateway.public import build_llm_completion_port


async def distill_conversation(
    session: AsyncSession,
    command: DistillConversationCommand,
) -> MemoryDraft | None:
    port = llm_distillation.LlmMemoryDistillation(
        session, build_llm_completion_port()
    )
    return await OrganizationalMemory(port).distill(command)
