"""Compatibility facade for governed read-only data queries."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyAuditTrail,
)
from app.contexts.foundations.integration.governed_data_query.contracts import (
    GovernedQueryRequest,
)
from app.contexts.foundations.integration.governed_data_query.entrypoints import operations

logger = logging.getLogger(__name__)

_MAX_ROWS = 1000
_MAX_COLS = 50
_MAX_TIMEOUT = 60


async def run_readonly_sql(
    db: AsyncSession,
    sql: str,
    *,
    actor_id: uuid.UUID | None,
    actor_role: str | None,
    source: str = "agent",
) -> dict[str, Any]:
    result = await operations.run_query(
        db,
        GovernedQueryRequest(
            sql=sql,
            actor_id=actor_id,
            actor_role=actor_role,
            source=source,
        ),
        audit=SQLAlchemyAuditTrail(db, logger=logger),
        max_rows=_MAX_ROWS,
        max_columns=_MAX_COLS,
        timeout_seconds=_MAX_TIMEOUT,
    )
    return result.to_dict()
