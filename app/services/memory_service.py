"""Compatibility facade for the Organizational Memory context."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.knowledge.organizational_memory.contracts import (
    DistillConversationCommand,
)
from app.contexts.foundations.knowledge.organizational_memory.domain.policies import (
    build_distillation_input,
)
from app.contexts.foundations.knowledge.organizational_memory.entrypoints.operations import (
    distill_conversation as _distill_conversation,
)


def build_distill_input(transcript: str) -> str:
    return build_distillation_input(transcript)


async def distill_conversation(
    db: AsyncSession, transcript: str, *, user_id: uuid.UUID | None = None
) -> str | None:
    draft = await _distill_conversation(
        db,
        DistillConversationCommand(transcript=transcript, principal_id=user_id),
    )
    return draft.content if draft is not None else None
