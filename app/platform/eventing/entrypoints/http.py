"""入站事件 HTTP 端点：``POST /internal/events``（docs/23 §3.2）。

服务身份鉴权（ES256 internal JWT，强制 ``events:receive`` scope）→ 幂等落库 → 202。
验签失败 401（``AuthenticationFailed`` 由全局处理器映射）、缺 scope 403（``HTTPException``，
平台端点不依赖 Context，直接用 FastAPI 原生错误）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.core.internal_token import verify_internal_token
from app.platform.eventing.inbox import EventEnvelope, get_inbox_projector, receive_event
from app.platform.eventing.relay import EVENTS_SCOPE
from app.platform.http_runtime import ok

router = APIRouter(tags=["eventing"])

_bearer = HTTPBearer(auto_error=True)  # 无 Authorization 头 → 403（FastAPI 默认）


def _require_events_scope(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(_bearer)],
) -> str:
    """验签服务令牌并强制 events:receive scope；返回签发方 service_id。"""
    claims = verify_internal_token(
        credentials.credentials, audience=get_settings().internal_jwt_issuer
    )
    if EVENTS_SCOPE not in claims.scope:
        raise HTTPException(status_code=403, detail=f"服务令牌缺少 {EVENTS_SCOPE} scope")
    return claims.service_id


@router.post("/internal/events", status_code=202)
async def receive_internal_event(
    envelope: EventEnvelope,
    db: Annotated[AsyncSession, Depends(get_db)],
    source: Annotated[str, Depends(_require_events_scope)],
) -> dict:
    """收下一条跨服务事件（幂等：同 event_id 重投只落一行）。

    首收且该类型注册了入站投影（如 ``expert.execution.completed.v1`` 唤醒停车 step）→ 同一事务内
    同步投影后再 commit；投影抛错 → 事务回滚（含 inbox 行）→ 5xx → 对端 relay 重投（docs/23 §6.3）。
    """
    accepted = await receive_event(db, envelope, source=source)
    if accepted:
        projector = get_inbox_projector(envelope.event_type)
        if projector is not None:
            await projector(db, envelope)
    await db.commit()
    return ok({"event_id": str(envelope.event_id), "accepted": accepted})
