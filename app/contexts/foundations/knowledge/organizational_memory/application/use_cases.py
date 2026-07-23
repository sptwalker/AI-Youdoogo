"""Organizational Memory application service."""

from __future__ import annotations

import logging

from app.contexts.foundations.knowledge.organizational_memory.application.ports import (
    MemoryDistillationPort,
)
from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
    MemoryDraft,
)

logger = logging.getLogger(__name__)


class OrganizationalMemory:
    def __init__(self, distillation: MemoryDistillationPort) -> None:
        self._distillation = distillation

    async def distill(self, command: DistillConversationCommand) -> MemoryDraft | None:
        if not command.transcript.strip():
            return None
        try:
            return await self._distillation.distill(command)
        except Exception:  # noqa: BLE001 - archive caller preserves raw source on failure
            logger.warning("对话记忆提炼失败，将回退存原始存档", exc_info=True)
            return None
