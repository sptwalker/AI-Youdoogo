"""数据接口注册表管理接口（F2，仅 admin）。密钥仅回显状态位，不回显值。"""

import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.contexts.business.operational_analytics.entrypoints import (
    operations as analytics,
)
from app.contexts.foundations.integration.connector_management.application.contracts import (
    RegisterConnector,
    UpdateConnector,
)
from app.contexts.foundations.integration.connector_management.entrypoints import operations
from app.platform.database import get_db
from app.platform.http_runtime import ok
from app.schemas.knowledge import DataSourceCreate, DataSourceUpdate

router = APIRouter(prefix="/data-sources", tags=["data-source"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[object, Depends(require_roles("admin"))]


@router.get("")
async def list_ds(db: DB, _: Admin) -> dict:
    """数据接口列表（密钥仅回显状态位）。"""
    snapshots = await operations.list_connectors(db)
    return ok([snapshot.to_dict() for snapshot in snapshots])


@router.post("")
async def create_ds(body: DataSourceCreate, db: DB, _: Admin) -> dict:
    """注册数据接口。secret_ref 存 .env 变量名。"""
    ds = await operations.register_connector(
        db,
        RegisterConnector(
            name=body.name,
            connector_type=body.type,
            code=body.code,
            department_id=body.department_id,
            config=body.config,
            secret_ref=body.secret_ref,
            owner_expert_id=body.owner_agent_id,
        ),
    )
    return ok({"id": str(ds.id), "name": ds.name, "code": ds.code})


@router.patch("/{ds_id}")
async def update_ds(ds_id: uuid.UUID, body: DataSourceUpdate, db: DB, _: Admin) -> dict:
    """改数据接口名/参数/密钥引用/启用。"""
    ds = await operations.update_connector(
        db,
        UpdateConnector(
            connector_id=ds_id,
            name=body.name,
            config=body.config,
            secret_ref=body.secret_ref,
            is_active=body.is_active,
            department_id=body.department_id,
            owner_expert_id=body.owner_agent_id,
        ),
    )
    return ok({"id": str(ds.id), "name": ds.name})


@router.delete("/{ds_id}")
async def delete_ds(ds_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """软删数据接口。"""
    await operations.delete_connector(db, ds_id)
    return ok()


@router.post("/{ds_id}/test")
async def test_ds(ds_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """测试数据接口连通性（用生效配置真跑一次，不落库、不回显密钥，P2-26）。"""
    connector = await operations.get_connector(db, ds_id)
    if connector.connector_type != "thinkingdata":
        return ok(
            {
                "status": "unsupported",
                "message": (
                    f"暂仅支持 thinkingdata 类型连通测试，当前类型 {connector.connector_type}"
                ),
            }
        )
    # ponytail: TD 连通复用运营分析的系统级 TD 读取校验（读系统配置的 TD 地址/密钥/日指标 SQL），
    # 非按本连接器 config 独立建连；多 TD 连接器时都测同一套系统 TD 配置。需按连接器独立建连再拆。
    result = await analytics.test_connector(db, date.today())
    return ok(result.to_dict())
