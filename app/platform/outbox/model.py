"""SQLAlchemy persistence model owned by the platform outbox."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin

_JSONB = JSON().with_variant(JSONB(), "postgresql")

OUTBOX_PENDING = "pending"
OUTBOX_PROCESSING = "processing"
OUTBOX_DONE = "done"
OUTBOX_FAILED = "failed"


class OutboxEvent(CommonMixin, Base):
    """Transactional event claimed by one leased worker and retried on failure."""

    __tablename__ = "outbox_event"
    __table_args__ = (
        Index("uq_outbox_dedupe", "dedupe_key", unique=True),
        Index("ix_outbox_poll", "status", "available_at", "lease_until"),
    )

    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    event_type: Mapped[str] = mapped_column(String(64))
    dedupe_key: Mapped[str] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict, server_default="{}")
    status: Mapped[str] = mapped_column(
        String(16), default=OUTBOX_PENDING, server_default=OUTBOX_PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_owner: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
