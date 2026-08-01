"""出站 HTTP Relay：把 outbox 事件投递给对端 Inbox（docs/23 §3.2）。

作为 ``ExternalEventHandler`` 挂在 outbox worker 的路由扩展缝上（``register_event_handler``）。
非 2xx / 超时即 ``raise`` → 现有 outbox 退避重试 / DLQ 全自动接管（不自建重试逻辑）。
**日志不回显 token / body 明文**（docs/23 §5 红线）。
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.internal_token import mint_internal_token
from app.platform.eventing.inbox import EventEnvelope
from app.platform.eventing.remote_step import GATEWAY_AUDIENCE, LLM_COMPLETE_SCOPE
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

    def _payload(self, event: OutboxEvent) -> dict[str, Any]:
        """出站 payload。默认原样出库；子类可注入投递期临时字段（不写回 OutboxEvent 行）。"""
        return event.payload or {}

    async def __call__(self, _session: AsyncSession, event: OutboxEvent) -> None:
        """投递一条事件。出站不碰 DB（session 未用）；失败上抛交 outbox 重试/DLQ。"""
        envelope = EventEnvelope(
            event_id=event.id,
            event_type=event.event_type,
            aggregate_type=event.aggregate_type,
            aggregate_id=event.aggregate_id,
            payload=self._payload(event),
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
    """按配置构造回环/远端 relay。transport 令牌 audience = 对端期望 aud（空回退本 issuer 走回环）。

    # ponytail: 回环 audience=本服务 issuer；跨仓填 event_inbox_peer_audience=对端 service_id。
    """
    settings = get_settings()
    return HttpInboxRelay(
        peer_url=settings.event_inbox_peer_url,
        audience=settings.event_inbox_peer_audience or settings.internal_jwt_issuer,
        source_service=settings.internal_jwt_issuer,
    )


class StepReadyRelay(HttpInboxRelay):
    """``workflow.step.ready.v1`` 专用 relay（docs/23 §6.3.3）。

    在**每次投递时**动态签发新鲜 callback_token 注入 payload 副本——expert 只持验签公钥、不能签发，
    故回执令牌须由 youdoo（私钥）签发、expert 原样 ``Bearer`` 回带、youdoo inbox 自验。令牌**绝不
    写回 OutboxEvent 行**（规避随行入库过期）；每次投递（含 outbox 重投）都新鲜签发 → 重投不过期。
    aud = 本服务 issuer（youdoo inbox 校验的 audience），与出站 Authorization 令牌同 audience。
    """

    def _payload(self, event: OutboxEvent) -> dict[str, Any]:
        settings = get_settings()
        callback_token = mint_internal_token(
            service_id=self._source,
            audience=settings.internal_jwt_issuer,
            scope=(EVENTS_SCOPE,),
        )
        # 只注入内存 payload 副本；不打印令牌明文（红线）。
        extra: dict[str, Any] = {"callback_token": callback_token}
        # 真·网关执行器转发（docs/23 §6.5）：门控开→投递期注入新鲜 gateway_token（aud=网关,
        # scope=llm:complete），expert 原样 Bearer 中继跑真模型；关→不注入→远端回落 echo。
        # 投递期注入（含 outbox 重投）→ 每次新鲜，天然解 exp≤300s 与停车长租约的过期矛盾。
        if settings.expert_forward_gateway_token:
            extra["gateway_token"] = mint_internal_token(
                service_id=self._source,
                audience=GATEWAY_AUDIENCE,
                scope=(LLM_COMPLETE_SCOPE,),
            )
        return {**(event.payload or {}), **extra}


def build_step_ready_relay_from_settings() -> StepReadyRelay:
    """按配置构造 step.ready relay。transport 令牌 audience = 对端期望 aud（空回退本服务 issuer）。

    callback_token（``_payload`` 注入）恒用本服务 issuer 作 aud——回发目标是本服务 inbox，自签自验。
    """
    settings = get_settings()
    return StepReadyRelay(
        peer_url=settings.event_inbox_peer_url,
        audience=settings.event_inbox_peer_audience or settings.internal_jwt_issuer,
        source_service=settings.internal_jwt_issuer,
    )
