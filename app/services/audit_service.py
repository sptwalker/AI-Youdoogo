"""审计留痕（docs/13 契约③ · F4a）：真人生效动作 + 配置/组织/权限变更强制落 audit_log。

追加式；detail 落库前对密钥字段打码；写审计失败绝不阻断主链（吞异常记日志）。
调用点在 API 层（有 CurrentUser 的 id + role_code）。
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)

_SECRET_HINT = ("secret", "password", "token", "api_key", "apikey", "access_key")


def _mask(detail: dict[str, Any] | None) -> dict[str, Any] | None:
    """key 含敏感子串则值打码为 ***（防密钥入审计表）。递归处理嵌套 dict。"""
    if not detail:
        return detail
    out: dict[str, Any] = {}
    for k, v in detail.items():
        lk = k.lower()
        if any(h in lk for h in _SECRET_HINT):
            out[k] = "***"
        elif isinstance(v, dict):
            out[k] = _mask(v)
        else:
            out[k] = v
    return out


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
    """写一条审计。失败重试一次仍不成则记 ERROR（不阻断主链，但可告警，H2.3）。"""
    log = AuditLog(
        actor_id=actor_id, actor_role=actor_role, action=action,
        target_type=target_type, target_id=target_id, summary=summary,
        detail=_mask(detail), result=result,
    )
    for attempt in (1, 2):  # 重试一次，缓解瞬时故障
        try:
            db.add(log)
            await db.commit()
            return
        except Exception:  # noqa: BLE001 - 审计失败不阻断主链，但要留痕可告警
            await db.rollback()
            if attempt == 2:
                # ERROR 级（非 warning）:审计是红线合规证据链，失败须可被监控告警
                logger.error("写审计最终失败 action=%s actor=%s", action, actor_id, exc_info=True)


async def list_audit_logs(
    db: AsyncSession,
    *,
    action: str | None = None,
    actor_id: uuid.UUID | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """审计流（按时间倒序，可按 action/actor 过滤）。"""
    stmt = select(AuditLog)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if actor_id:
        stmt = stmt.where(AuditLog.actor_id == actor_id)
    stmt = stmt.order_by(AuditLog.create_time.desc()).limit(limit)
    return [
        {
            "id": str(a.id), "actor_id": str(a.actor_id) if a.actor_id else None,
            "actor_role": a.actor_role, "action": a.action,
            "target_type": a.target_type, "target_id": str(a.target_id) if a.target_id else None,
            "summary": a.summary, "detail": a.detail, "result": a.result,
            "create_time": a.create_time.isoformat(),
        }
        for a in (await db.execute(stmt)).scalars()
    ]
