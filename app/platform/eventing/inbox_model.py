"""入站事件幂等去重表（Phase 3 事件传输门禁 / docs/23 §3.2）。

跨服务事件交接的**入站半边**：对端 Relay POST 来的事件在此落库。``event_id``（源 outbox 事件 id）
唯一约束 = 入站幂等去重键——同一事件重复投递（网络重试 / DLQ 重放）只落一行，逻辑上只处理一次。
"""

import uuid
from typing import Any

from sqlalchemy import JSON, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.platform.database.model import Base, CommonMixin

_JSONB = JSON().with_variant(JSONB(), "postgresql")

INBOX_RECEIVED = "received"
INBOX_PROCESSED = "processed"


class InboxEvent(CommonMixin, Base):
    """一条收下的跨服务事件；``event_id`` 唯一 = 入站幂等去重键。``create_time`` 即到达时刻。"""

    __tablename__ = "inbox_event"
    __table_args__ = (Index("uq_inbox_event_id", "event_id", unique=True),)

    event_id: Mapped[uuid.UUID] = mapped_column(Uuid)  # 源 outbox 事件 id（幂等键）
    event_type: Mapped[str] = mapped_column(String(64))
    aggregate_type: Mapped[str] = mapped_column(String(32))
    aggregate_id: Mapped[uuid.UUID] = mapped_column(Uuid)
    payload: Mapped[dict[str, Any]] = mapped_column(_JSONB, default=dict, server_default="{}")
    source_service: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(
        String(16), default=INBOX_RECEIVED, server_default=INBOX_RECEIVED
    )
