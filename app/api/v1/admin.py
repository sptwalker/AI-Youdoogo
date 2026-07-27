"""系统管理接口（F4a，仅 admin）：审计流 + 可编辑配置读写。

前端管理台（系统日志/配置编辑 UI）留 F5，本文件只出后端读写端点。
"""

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.contexts.foundations.governance.audit_trail.public import (
    AuditTrailQuery,
    query_audit_trail_page,
)
from app.contexts.foundations.governance.system_configuration.connectivity.public import (
    test_external_connectivity,
)
from app.contexts.foundations.governance.system_configuration.public import (
    UpdateConfigCommand,
    list_configurations,
    update_configuration,
)
from app.contexts.foundations.identity.public import IdentityUserResult
from app.core.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(tags=["admin"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[IdentityUserResult, Depends(require_roles("admin"))]


@router.get("/audit-logs")
async def list_audit_logs(
    db: DB,
    _: Admin,
    action: Annotated[str | None, Query()] = None,
    actor_id: Annotated[uuid.UUID | None, Query()] = None,
    start: Annotated[datetime | None, Query()] = None,
    end: Annotated[datetime | None, Query()] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> dict:
    """审计流（按时间倒序，可按 action/actor/时间范围过滤，服务端翻页）。"""
    page = await query_audit_trail_page(
        db,
        AuditTrailQuery(
            action=action,
            actor_id=actor_id,
            start=start,
            end=end,
            limit=limit,
            offset=offset,
        ),
    )
    return ok(
        {
            "items": [
                {
                    "id": str(record.record_id),
                    "actor_id": str(record.actor_id) if record.actor_id else None,
                    "actor_role": record.actor_role,
                    "action": record.action,
                    "target_type": record.target_type,
                    "target_id": str(record.target_id) if record.target_id else None,
                    "summary": record.summary,
                    "detail": dict(record.detail) if record.detail is not None else None,
                    "result": record.result,
                    "create_time": record.occurred_at,
                }
                for record in page.items
            ],
            "total": page.total,
        }
    )


@router.get("/configs")
async def list_configs(db: DB, _: Admin) -> dict:
    """可编辑配置列表。"""
    configs = await list_configurations(db)
    return ok(
        [
            {
                "key": config.key,
                "value": "" if config.is_secret else config.value,
                "value_type": config.value_type,
                "category": config.category,
                "is_editable": config.is_editable,
                "is_secret": config.is_secret,
                "is_set": config.is_set,
            }
            for config in configs
        ]
    )


class ConfigUpdate(BaseModel):
    """配置改值（value 类型由该项 value_type 决定）。"""

    value: Any


@router.patch("/configs/{key}")
async def update_config(key: str, body: ConfigUpdate, db: DB, admin: Admin) -> dict:
    """改配置即时生效（内部落审计）。"""
    config = await update_configuration(
        db,
        UpdateConfigCommand(
            key=key,
            value=body.value,
            updated_by=admin.id,
            actor_role=admin.role_code,
        ),
    )
    return ok({"key": config.key, "value": config.value})


@router.get("/admin/connectivity")
async def test_connectivity(_: Admin) -> dict:
    """外部依赖连通性测试（LLM/飞书/ThinkingData），只回状态+延迟，不回显密钥。"""
    return ok([result.to_dict() for result in await test_external_connectivity()])
