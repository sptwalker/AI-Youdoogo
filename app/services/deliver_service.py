"""Compatibility facade for Deliverable Management."""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

import app.platform.object_storage.gateway as storage
from app.agents.contracts import ExecutionContext, SkillResult
from app.contexts.foundations.execution.deliverable_management.application.formatting import (
    build_bytes as _build_bytes,
)
from app.contexts.foundations.execution.deliverable_management.application.formatting import (
    markdown_table_to_rows as _markdown_table_to_rows,
)
from app.contexts.foundations.execution.deliverable_management.application.formatting import (
    safe_file_name as _safe_name,
)
from app.contexts.foundations.execution.deliverable_management.entrypoints import (
    agent_capability,
)
from app.contexts.foundations.execution.deliverable_management.entrypoints.agent_capability import (
    PROMPT_SECTION,
    DeliveryArgs,
    DeliverySkillExecutor,
    parse,
)
from app.contexts.foundations.execution.deliverable_management.public import (
    list_deliverables as _list_deliverables,
)
from app.models.agent import AgentRole
from app.services import config_service

ProtocolResult = SkillResult


async def execute(
    db: AsyncSession,
    initiator: AgentRole,
    output: str,
    *,
    user_id: uuid.UUID | None = None,
    execution_context: ExecutionContext | None = None,
) -> SkillResult:
    """Preserve the legacy text-protocol entrypoint and its patchable storage seam."""
    return await agent_capability.execute(
        db,
        initiator,
        output,
        user_id=user_id,
        execution_context=execution_context,
        feature_flag_resolver=config_service.resolve,
        executor_factory=lambda: DeliverySkillExecutor(publisher=storage.put_object),
    )


async def list_deliverables(
    db: AsyncSession,
    owner_user_id: uuid.UUID,
    *,
    limit: int = 50,
) -> list[dict[str, str | int]]:
    """Preserve the legacy desktop projection shape."""
    rows = await _list_deliverables(db, owner_user_id, limit=limit)
    return [
        {
            "id": str(row.deliverable_id),
            "file_name": row.file_name,
            "file_format": row.file_format.value,
            "agent_name": row.agent_name,
            "file_size": row.file_size,
            "create_time": row.create_time.isoformat(),
        }
        for row in rows
    ]


__all__ = [
    "DeliveryArgs",
    "DeliverySkillExecutor",
    "PROMPT_SECTION",
    "ProtocolResult",
    "_build_bytes",
    "_markdown_table_to_rows",
    "_safe_name",
    "execute",
    "list_deliverables",
    "parse",
    "storage",
]
