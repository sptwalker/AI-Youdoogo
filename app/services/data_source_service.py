"""数据接口注册表管理（F2）：CRUD。密钥走 secret_ref 指向 .env，绝不存明文。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.models.knowledge import DataSource

VALID_TYPES = ("thinkingdata", "feishu_bitable", "feishu_docx", "excel", "http_api")


async def get_ds(db: AsyncSession, ds_id: uuid.UUID) -> DataSource:
    ds = await db.get(DataSource, ds_id)
    if ds is None or ds.is_delete:
        raise AppError("数据接口不存在", code=404, status_code=404)
    return ds


async def create_ds(
    db: AsyncSession,
    *,
    name: str,
    type: str,
    code: str | None = None,
    department_id: uuid.UUID | None = None,
    config: dict[str, Any] | None = None,
    secret_ref: str | None = None,
) -> DataSource:
    if type not in VALID_TYPES:
        raise AppError(f"type 仅支持 {'/'.join(VALID_TYPES)}")
    ds = DataSource(
        name=name, code=code or f"ds_{uuid.uuid4().hex[:8]}", type=type,
        department_id=department_id, config=config or {}, secret_ref=secret_ref,
    )
    db.add(ds)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError("数据接口编码已存在", code=409, status_code=409) from exc
    await db.refresh(ds)
    return ds


async def update_ds(
    db: AsyncSession,
    ds_id: uuid.UUID,
    *,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    secret_ref: str | None = None,
    is_active: bool | None = None,
) -> DataSource:
    ds = await get_ds(db, ds_id)
    if name is not None:
        ds.name = name
    if config is not None:
        ds.config = config
    if secret_ref is not None:
        ds.secret_ref = secret_ref
    if is_active is not None:
        ds.is_active = is_active
    await db.commit()
    await db.refresh(ds)
    return ds


async def delete_ds(db: AsyncSession, ds_id: uuid.UUID) -> None:
    ds = await get_ds(db, ds_id)
    ds.is_delete = True
    await db.commit()


def _secret_status(secret_ref: str | None) -> str:
    """密钥状态（脱敏）：not_set / configured / missing（.env 无此变量）。不回显值。"""
    if not secret_ref:
        return "not_set"
    return "configured" if getattr(get_settings(), secret_ref.lower(), "") else "missing"


async def list_ds(db: AsyncSession) -> list[dict[str, Any]]:
    """数据接口列表（密钥仅回显状态位，不回显值）。"""
    stmt = (
        select(DataSource)
        .where(DataSource.is_delete.is_(False))
        .order_by(DataSource.create_time)
    )
    rows = list((await db.execute(stmt)).scalars())
    return [
        {
            "id": str(ds.id), "name": ds.name, "code": ds.code, "type": ds.type,
            "department_id": str(ds.department_id) if ds.department_id else None,
            "config": ds.config, "secret_ref": ds.secret_ref,
            "secret_status": _secret_status(ds.secret_ref), "is_active": ds.is_active,
        }
        for ds in rows
    ]
