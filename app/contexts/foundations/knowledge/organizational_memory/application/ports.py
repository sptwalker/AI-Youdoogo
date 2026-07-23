"""Organizational Memory distillation port."""

from __future__ import annotations

from typing import Protocol

from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
    MemoryDraft,
)


class MemoryDistillationPort(Protocol):
    async def distill(self, command: DistillConversationCommand) -> MemoryDraft | None: ...
