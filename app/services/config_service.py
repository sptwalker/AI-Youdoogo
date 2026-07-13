"""可编辑配置解析/管理（docs/13 §3 · F4a）。

两层解析：sys_config(DB) → 调用方传入的 default（通常来自 Settings/.env 兜底）。
非密配置改后即时生效（无进程级缓存，每次查库）；改配置写审计。密钥不入本表。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.sys_config import SysConfig
from app.services import audit_service


async def _get(db: AsyncSession, key: str) -> SysConfig | None:
    stmt = select(SysConfig).where(SysConfig.key == key, SysConfig.is_delete.is_(False))
    return (await db.execute(stmt)).scalar_one_or_none()


async def resolve(db: AsyncSession, key: str, default: Any = None) -> Any:
    """取配置值：DB 有则用 DB，否则用 default（.env 兜底由调用方给）。"""
    cfg = await _get(db, key)
    return cfg.value if cfg is not None else default


async def list_configs(db: AsyncSession) -> list[dict[str, Any]]:
    """可编辑配置列表（本表不存密钥，直接回显）。"""
    stmt = (
        select(SysConfig)
        .where(SysConfig.is_delete.is_(False))
        .order_by(SysConfig.category, SysConfig.key)
    )
    return [
        {
            "key": c.key, "value": c.value, "value_type": c.value_type,
            "category": c.category, "is_editable": c.is_editable,
        }
        for c in (await db.execute(stmt)).scalars()
    ]


async def set_config(
    db: AsyncSession,
    key: str,
    value: Any,
    *,
    updated_by: uuid.UUID | None,
    actor_role: str | None,
) -> SysConfig:
    """改配置即时生效（仅 is_editable 可改）+ 落审计。"""
    cfg = await _get(db, key)
    if cfg is None:
        raise AppError("配置项不存在", code=404, status_code=404)
    if not cfg.is_editable:
        raise AppError("该配置项不可编辑")
    cfg.value = value
    cfg.updated_by = updated_by
    await db.commit()
    await db.refresh(cfg)
    await audit_service.audit(
        db, actor_id=updated_by, actor_role=actor_role, action="config.update",
        summary=f"修改配置 {key}", target_type="sys_config", target_id=cfg.id,
        detail={"key": key},
    )
    return cfg
