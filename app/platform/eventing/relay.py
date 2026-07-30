"""出站 HTTP Relay：把 outbox 事件投递给对端 Inbox（docs/23 §3.2）。

作为 ``ExternalEventHandler`` 挂在 outbox worker 的路由扩展缝上（``register_event_handler``）。
非 2xx / 超时即 ``raise`` → 现有 outbox 退避重试 / DLQ 全自动接管（不自建重试逻辑）。
**日志不回显 token / body 明文**（docs/23 §5 红线）。
"""

from __future__ import annotations

import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.platform.eventing.inbox import EventEnvelope
from app.platform.outbox.model import OutboxEvent

logger = logging.getLogger(__name__)

EVENTS_SCOPE = "events:receive"


class HttpInboxRelay:
    """把一条 ``OutboxEvent`` 签发服务令牌后 POST 到 ``{peer}/internal/events``。"""

    def __init__(
        self,
        *,
        peer_url: str,
        audience: str,
        source_service: str,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._url = peer_url.rstrip("/") + "/internal/events"
        self._audience = audience
        self._source = source_service
        self._timeout = timeout
        self._transport = transport  # 注入点：门禁演练用 ASGITransport 回环，生产为 None（真网络）

    async def __call__(self, _session: AsyncSession, event: OutboxEvent) -> None:
        """投递一条事件。出站不碰 DB（session 未用）；失败上抛交 outbox 重试/DLQ。"""
        envelope = EventEnvelope(
            event_id=event.id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=event.payload or {},
            dedupe_key=event.dedupe_key,
        )
        token = mint_internal_token(
            service_id=self._source,
            audience=self._audience,
            scope=(EVENTS_SCOPE,),
        )
        async with httpx.AsyncClient(timeout=self._timeout, transport=self._transport) as client:
            resp = await client.post(
                self._url,
                headers={"Authorization": f"Bearer {token}"},
                json=envelope.model_dump(mode="json"),
            )
        if resp.status_code >= 300:
            # 只记状态码与 event_id，不记 token / body（红线）
            logger.warning("event relay 投递失败 event=%s status=%s", event.id, resp.status_code)
            raise RuntimeError(f"inbox 返回 {resp.status_code}")


def build_relay_from_settings() -> HttpInboxRelay:
    """按配置构造回环/远端 relay。audience 与 source 用本服务 issuer（回环自签自验）。

    # ponytail: 回环 audience=本服务 issuer；真实远端消费者上线时按对端 service_id 配 audience。
    """
    settings = get_settings()
    return HttpInboxRelay(
        peer_url=settings.event_inbox_peer_url,
        audience=settings.internal_jwt_issuer,
        source_service=settings.internal_jwt_issuer,
    )
