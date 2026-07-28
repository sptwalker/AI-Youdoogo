"""Request-scoped Organizational Memory operations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

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
from app.contexts.foundations.model_gateway.contracts.completion import LlmCompletionPort
from app.contexts.foundations.model_gateway.public import build_local_llm_completion_port


async def distill_conversation(
    session: AsyncSession,
    command: DistillConversationCommand,
    *,
    port: LlmCompletionPort | None = None,
    llm_factory: Callable[..., Any] | None = None,
) -> MemoryDraft | None:
    completion_port = port or build_local_llm_completion_port(
        llm_factory=llm_factory,
    )
    distiller = llm_distillation.LlmMemoryDistillation(
        session,
        completion_port,
    )
    return await OrganizationalMemory(distiller).distill(command)
