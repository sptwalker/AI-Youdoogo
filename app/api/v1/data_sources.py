"""数据接口注册表管理接口（F2，仅 admin）。密钥仅回显状态位，不回显值。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.system import SysUser
from app.platform.http_runtime import ok
from app.schemas.knowledge import DataSourceCreate, DataSourceUpdate
from app.services import data_source_service as ds_svc

router = APIRouter(prefix="/data-sources", tags=["data-source"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


@router.get("")
async def list_ds(db: DB, _: Admin) -> dict:
    """数据接口列表（密钥仅回显状态位）。"""
    return ok(await ds_svc.list_ds(db))


@router.post("")
async def create_ds(body: DataSourceCreate, db: DB, _: Admin) -> dict:
    """注册数据接口。secret_ref 存 .env 变量名。"""
    ds = await ds_svc.create_ds(
        db,
        name=body.name,
        type=body.type,
        code=body.code,
        department_id=body.department_id,
        config=body.config,
        secret_ref=body.secret_ref,
        owner_agent_id=body.owner_agent_id,
    )
    return ok({"id": str(ds.id), "name": ds.name, "code": ds.code})


@router.patch("/{ds_id}")
async def update_ds(ds_id: uuid.UUID, body: DataSourceUpdate, db: DB, _: Admin) -> dict:
    """改数据接口名/参数/密钥引用/启用。"""
    ds = await ds_svc.update_ds(
        db, ds_id,
        name=body.name, config=body.config,
        secret_ref=body.secret_ref, is_active=body.is_active,
        department_id=body.department_id, owner_agent_id=body.owner_agent_id,
    )
    return ok({"id": str(ds.id), "name": ds.name})


@router.delete("/{ds_id}")
async def delete_ds(ds_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """软删数据接口。"""
    await ds_svc.delete_ds(db, ds_id)
    return ok()
