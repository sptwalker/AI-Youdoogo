"""Request-scoped composition for the Audit Trail context."""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail.infrastructure.sqlalchemy_adapter import (
    SQLAlchemyAuditTrail,
)

logger = logging.getLogger(__name__)


def build_audit_trail(session: AsyncSession) -> SQLAlchemyAuditTrail:
    """Build the canonical audit boundary over the caller's session."""
    return SQLAlchemyAuditTrail(session, logger=logger)
