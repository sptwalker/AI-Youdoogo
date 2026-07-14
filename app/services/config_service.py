"""可编辑配置解析/管理（docs/13 §3 · F4a；F5+ 密钥可 UI 填写）。

两层解析：sys_config(DB) → 调用方传入的 default（通常来自 Settings/.env 兜底）。
改配置即时生效 + 写审计 + 同步 runtime_config 覆盖（供 LLM/飞书/embedding 等读取）。
密钥类(is_secret)：值存本表但 list 读时脱敏（不回显明文），审计 detail 打码。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import runtime_config
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


async def all_values(db: AsyncSession) -> dict[str, Any]:
    """全部配置 key→value（供启动时载入 runtime_config 覆盖层）。"""
    stmt = select(SysConfig).where(SysConfig.is_delete.is_(False))
    return {c.key: c.value for c in (await db.execute(stmt)).scalars()}


def _is_set(value: Any) -> bool:
    return value is not None and value != ""


async def list_configs(db: AsyncSession) -> list[dict[str, Any]]:
    """配置列表。密钥项(is_secret)不回显明文，仅回 is_set 状态位。"""
    stmt = (
        select(SysConfig)
        .where(SysConfig.is_delete.is_(False))
        .order_by(SysConfig.category, SysConfig.key)
    )
    out: list[dict[str, Any]] = []
    for c in (await db.execute(stmt)).scalars():
        out.append({
            "key": c.key,
            "value": "" if c.is_secret else c.value,  # 密钥脱敏，不回显
            "value_type": c.value_type, "category": c.category,
            "is_editable": c.is_editable, "is_secret": c.is_secret,
            "is_set": _is_set(c.value),  # 是否已配置（不泄露值）
        })
    return out


async def set_config(
    db: AsyncSession,
    key: str,
    value: Any,
    *,
    updated_by: uuid.UUID | None,
    actor_role: str | None,
) -> SysConfig:
    """改配置即时生效（仅 is_editable 可改）+ 同步覆盖层 + 落审计。"""
    cfg = await _get(db, key)
    if cfg is None:
        raise AppError("配置项不存在", code=404, status_code=404)
    if not cfg.is_editable:
        raise AppError("该配置项不可编辑")
    cfg.value = value
    cfg.updated_by = updated_by
    await db.commit()
    await db.refresh(cfg)
    runtime_config.set_override(key, value)  # 同步本进程覆盖，立即生效
    await audit_service.audit(
        db, actor_id=updated_by, actor_role=actor_role, action="config.update",
        summary=f"修改配置 {key}", target_type="sys_config", target_id=cfg.id,
        detail={"key": key},  # 只记 key，不记值（_mask 另兜底）
    )
    return cfg
