"""AI 模型卡片管理接口（仅 admin）：卡片化多 Provider 动态配置。

每次增删改/启停/设主用后同步 factory（卡片推进 LLM 网关）+ 落审计（密钥打码）。
密钥仅回显 hint + 状态位，不回显明文。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_roles
from app.contexts.foundations.governance.system_configuration.ai_provider_management.public import (
    CreateProviderCommand,
    ProviderActor,
    UpdateProviderCommand,
    set_primary_provider,
    test_all_provider_records,
    test_provider_record,
    toggle_provider,
)
from app.contexts.foundations.governance.system_configuration.ai_provider_management.public import (
    create_provider as create_provider_operation,
)
from app.contexts.foundations.governance.system_configuration.ai_provider_management.public import (
    delete_provider as delete_provider_operation,
)
from app.contexts.foundations.governance.system_configuration.ai_provider_management.public import (
    list_providers as list_provider_records,
)
from app.contexts.foundations.governance.system_configuration.ai_provider_management.public import (
    update_provider as update_provider_operation,
)
from app.contexts.foundations.identity.public import IdentityUserResult
from app.core.database import get_db
from app.platform.http_runtime import ok

router = APIRouter(prefix="/ai-providers", tags=["ai-provider"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[IdentityUserResult, Depends(require_roles("admin"))]


class ProviderCreate(BaseModel):
    """新增卡片。"""

    name: str = Field(min_length=1, max_length=64)
    tier: str = Field(default="daily")
    base_url: str = Field(min_length=1, max_length=512)
    api_key: str = Field(default="", max_length=512)
    model: str = Field(min_length=1, max_length=128)


class ProviderUpdate(BaseModel):
    """改卡片（api_key 空表示不改，保留原 Key）。"""

    name: str | None = Field(default=None, max_length=64)
    tier: str | None = None
    base_url: str | None = Field(default=None, max_length=512)
    api_key: str | None = Field(default=None, max_length=512)
    model: str | None = Field(default=None, max_length=128)


class ToggleBody(BaseModel):
    active: bool


def _actor(admin: IdentityUserResult) -> ProviderActor:
    return ProviderActor(actor_id=admin.id, role_code=admin.role_code)


@router.get("")
async def list_providers(db: DB, _: Admin) -> dict:
    """卡片列表（密钥脱敏）。"""
    return ok([provider.to_dict() for provider in await list_provider_records(db)])


@router.post("")
async def create_provider(body: ProviderCreate, db: DB, admin: Admin) -> dict:
    """新建卡片。"""
    card = await create_provider_operation(
        db,
        CreateProviderCommand(
            name=body.name,
            tier=body.tier,
            base_url=body.base_url,
            api_key=body.api_key,
            model=body.model,
            actor=_actor(admin),
        ),
    )
    return ok({"id": str(card.provider_id), "name": card.name, "tier": card.tier})


@router.patch("/{provider_id}")
async def update_provider(
    provider_id: uuid.UUID, body: ProviderUpdate, db: DB, admin: Admin
) -> dict:
    """改卡片。"""
    card = await update_provider_operation(
        db,
        UpdateProviderCommand(
            provider_id=provider_id,
            name=body.name,
            tier=body.tier,
            base_url=body.base_url,
            api_key=body.api_key,
            model=body.model,
            actor=_actor(admin),
        ),
    )
    return ok({"id": str(card.provider_id), "name": card.name})


@router.delete("/{provider_id}")
async def delete_provider(provider_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """软删卡片。"""
    await delete_provider_operation(db, provider_id, actor=_actor(admin))
    return ok()


@router.post("/{provider_id}/test")
async def test_provider(provider_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """连通测试（落状态，不改注册）。"""
    return ok((await test_provider_record(db, provider_id)).to_dict())


@router.post("/{provider_id}/primary")
async def set_primary(provider_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """设为该档位主用。"""
    card = await set_primary_provider(db, provider_id, actor=_actor(admin))
    return ok({"id": str(card.provider_id)})


@router.post("/{provider_id}/toggle")
async def toggle_active(provider_id: uuid.UUID, body: ToggleBody, db: DB, admin: Admin) -> dict:
    """启用/禁用卡片。"""
    card = await toggle_provider(
        db,
        provider_id,
        body.active,
        actor=_actor(admin),
    )
    return ok({"id": str(card.provider_id), "is_active": card.is_active})


@router.post("/test-all")
async def test_all(db: DB, _: Admin) -> dict:
    """一键检测所有卡片（绿/红/灰）。"""
    return ok([result.to_dict() for result in await test_all_provider_records(db)])
