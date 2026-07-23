"""One-way compatibility facade for the Audit Trail context."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail.contracts.audit import (
    AppendAuditRecordCommand,
    AuditTrailQuery,
)
from app.contexts.foundations.governance.audit_trail.domain.redaction import mask_secrets
from app.contexts.foundations.governance.audit_trail.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyAuditTrail,
)

logger = logging.getLogger(__name__)


def _mask(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    return cast(dict[str, Any] | None, mask_secrets(detail))


async def audit(
    db: AsyncSession,
    *,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    action: str,
    summary: str,
    target_type: str | None = None,
    target_id: uuid.UUID | None = None,
    detail: dict[str, Any] | None = None,
    result: str = "ok",
) -> None:
    await SQLAlchemyAuditTrail(db, logger=logger).append(
        AppendAuditRecordCommand(
            actor_id=actor_id,
            actor_role=actor_role,
            action=action,
            summary=summary,
            target_type=target_type,
            target_id=target_id,
            detail=detail,
            result=result,
        )
    )


async def list_audit_logs(
    db: AsyncSession,
    *,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    records = await SQLAlchemyAuditTrail(db, logger=logger).query(
        AuditTrailQuery(action=action, actor_id=actor_id, limit=limit)
    )
    return [
        {
            "id": str(record.record_id),
            "actor_id": str(record.actor_id) if record.actor_id else None,
            "actor_role": record.actor_role,
            "action": record.action,
            "target_type": record.target_type,
            "target_id": str(record.target_id) if record.target_id else None,
            "summary": record.summary,
            "detail": dict(record.detail) if isinstance(record.detail, Mapping) else None,
            "result": record.result,
            "create_time": record.occurred_at,
        }
        for record in records
    ]
