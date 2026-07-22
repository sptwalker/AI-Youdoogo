"""数据接口注册表管理（F2）：CRUD。密钥走 secret_ref 指向 .env，绝不存明文。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import ConflictDetected, ResourceNotFound, RuleViolation
from app.core.config import get_settings
from app.models.agent import AgentRole
from app.models.knowledge import DataSource

VALID_TYPES = ("thinkingdata", "feishu_bitable", "feishu_docx", "excel", "http_api")


async def _refresh_env(db: AsyncSession) -> None:
    """数据接口变更后刷新环境快照（docs/13 §9）。局部 import 防循环依赖；内部吞异常。"""
    from app.services import environment_service

    await environment_service.refresh_env_doc(db)


async def _check_owner_agent(db: AsyncSession, agent_id: uuid.UUID) -> None:
    """显式校验对接 AI 存在（否则 FK 违约会被误报成"编码已存在"409）。"""
    agent = await db.get(AgentRole, agent_id)
    if agent is None or agent.is_delete:
        raise ResourceNotFound("指定的对接AI不存在")


async def get_ds(db: AsyncSession, ds_id: uuid.UUID) -> DataSource:
    ds = await db.get(DataSource, ds_id)
    if ds is None or ds.is_delete:
        raise ResourceNotFound("数据接口不存在")
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
    owner_agent_id: uuid.UUID | None = None,
) -> DataSource:
    if type not in VALID_TYPES:
        raise RuleViolation(f"type 仅支持 {'/'.join(VALID_TYPES)}")
    if owner_agent_id is not None:
        await _check_owner_agent(db, owner_agent_id)
    ds = DataSource(
        name=name, code=code or f"ds_{uuid.uuid4().hex[:8]}", type=type,
        department_id=department_id, config=config or {}, secret_ref=secret_ref,
        owner_agent_id=owner_agent_id,
    )
    db.add(ds)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise ConflictDetected("数据接口编码已存在") from exc
    await db.refresh(ds)
    await _refresh_env(db)
    return ds


async def update_ds(
    db: AsyncSession,
    ds_id: uuid.UUID,
    *,
    name: str | None = None,
    config: dict[str, Any] | None = None,
    secret_ref: str | None = None,
    is_active: bool | None = None,
    department_id: uuid.UUID | None = None,
    owner_agent_id: uuid.UUID | None = None,
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
    if department_id is not None:  # F5c 改部门
        ds.department_id = department_id
    if owner_agent_id is not None:  # 指派对接AI（暂不支持置空回未指派）
        await _check_owner_agent(db, owner_agent_id)
        ds.owner_agent_id = owner_agent_id
    await db.commit()
    await db.refresh(ds)
    await _refresh_env(db)
    return ds


async def delete_ds(db: AsyncSession, ds_id: uuid.UUID) -> None:
    ds = await get_ds(db, ds_id)
    ds.is_delete = True
    await db.commit()
    await _refresh_env(db)


def _secret_status(secret_ref: str | None) -> str:
    """密钥状态（脱敏）：not_set / configured / missing（.env 无此变量）。不回显值。"""
    if not secret_ref:
        return "not_set"
    return "configured" if getattr(get_settings(), secret_ref.lower(), "") else "missing"


async def list_ds(db: AsyncSession) -> list[dict[str, Any]]:
    """数据接口列表（密钥仅回显状态位，不回显值）。含对接AI名称。"""
    stmt = (
        select(DataSource)
        .where(DataSource.is_delete.is_(False))
        .order_by(DataSource.create_time)
    )
    rows = list((await db.execute(stmt)).scalars())
    # 对接AI名称一次查全（避免 N+1）
    agent_ids = {ds.owner_agent_id for ds in rows if ds.owner_agent_id}
    names: dict[uuid.UUID, str] = {}
    if agent_ids:
        names = {
            a.id: a.name
            for a in (
                await db.execute(select(AgentRole).where(AgentRole.id.in_(agent_ids)))
            ).scalars()
        }
    return [
        {
            "id": str(ds.id), "name": ds.name, "code": ds.code, "type": ds.type,
            "department_id": str(ds.department_id) if ds.department_id else None,
            "config": ds.config, "secret_ref": ds.secret_ref,
            "secret_status": _secret_status(ds.secret_ref), "is_active": ds.is_active,
            "owner_agent_id": str(ds.owner_agent_id) if ds.owner_agent_id else None,
            "owner_agent_name": names.get(ds.owner_agent_id) if ds.owner_agent_id else None,
        }
        for ds in rows
    ]
