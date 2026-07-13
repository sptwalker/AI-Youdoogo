"""系统管理接口（F4a，仅 admin）：审计流 + 可编辑配置读写。

前端管理台（系统日志/配置编辑 UI）留 F5，本文件只出后端读写端点。
"""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.core.database import get_db
from app.core.exceptions import ok
from app.models.system import SysUser
from app.services import audit_service, config_service

router = APIRouter(tags=["admin"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


@router.get("/audit-logs")
async def list_audit_logs(
    db: DB,
    _: Admin,
    action: Annotated[str | None, Query()] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict:
    """审计流（按时间倒序，可按 action/actor 过滤）。"""
    return ok(
        await audit_service.list_audit_logs(db, action=action, actor_id=actor_id, limit=limit)
    )


@router.get("/configs")
async def list_configs(db: DB, _: Admin) -> dict:
    """可编辑配置列表。"""
    return ok(await config_service.list_configs(db))


class ConfigUpdate(BaseModel):
    """配置改值（value 类型由该项 value_type 决定）。"""

    value: Any


@router.patch("/configs/{key}")
async def update_config(key: str, body: ConfigUpdate, db: DB, admin: Admin) -> dict:
    """改配置即时生效（内部落审计）。"""
    cfg = await config_service.set_config(
        db, key, body.value, updated_by=admin.id, actor_role=admin.role_code
    )
    return ok({"key": cfg.key, "value": cfg.value})
