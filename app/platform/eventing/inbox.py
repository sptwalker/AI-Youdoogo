"""入站事件的线协议 + 幂等落库 + 平凡 demo 消费者（docs/23 §3.2）。

``EventEnvelope`` 是 Relay↔Inbox 的消费者驱动线协议（两侧逐字对齐，同 Phase 1/2 做法）。
``receive_event`` 幂等落库（INSERT-or-ignore）；``process_pending`` 是门禁用的平凡消费者，
只证"逻辑事件跨重投/重放仍处理一次"——真实入站投影是 Phase 3/4 Runtime 的活。
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.platform.eventing.inbox_model import INBOX_PROCESSED, INBOX_RECEIVED, InboxEvent


class EventEnvelope(BaseModel):
    """跨服务事件线协议：Relay 由 OutboxEvent 构造，Inbox 端解析。"""

    event_id: uuid.UUID
    event_type: str
    aggregate_type: str
    aggregate_id: uuid.UUID
    payload: dict[str, Any] = {}
    dedupe_key: str


async def receive_event(db: AsyncSession, envelope: EventEnvelope, *, source: str) -> bool:
    """幂等落库一条入站事件。返回 True=首次收下；False=已收过（同 event_id 去重，不重复处理）。

    镜像 outbox.enqueue 的 select→begin_nested→IntegrityError 兜底：并发同 event_id 也只落一行。
    """
    existing = (
        await db.execute(select(InboxEvent).where(InboxEvent.event_id == envelope.event_id))
    ).scalar_one_or_none()
    if existing is not None:
        return False
    row = InboxEvent(
        event_id=envelope.event_id,
        event_type=envelope.event_type,
        aggregate_type=envelope.aggregate_type,
        aggregate_id=envelope.aggregate_id,
        payload=envelope.payload,
        source_service=source,
    )
    try:
        async with db.begin_nested():
            db.add(row)
            await db.flush()
    except IntegrityError:
        return False  # 并发插入撞唯一约束 = 已收
    return True


async def process_pending(db: AsyncSession, *, limit: int = 100) -> int:
    """平凡 demo 消费者：received→processed，返回处理条数（门禁证"逻辑事件只处理一次"）。

    # ponytail: 只翻状态标记，不做真实业务投影——真实入站投影/乱序重排语义留 Phase 3/4 Runtime。
    """
    rows = list(
        (
            await db.execute(
                select(InboxEvent.id)
                .where(InboxEvent.status == INBOX_RECEIVED)
                .limit(limit)
            )
        ).scalars()
    )
    if not rows:
        return 0
    await db.execute(
        update(InboxEvent)
        .where(InboxEvent.id.in_(rows))
        .values(status=INBOX_PROCESSED)
        .execution_options(synchronize_session=False)
    )
    await db.flush()
    return len(rows)
