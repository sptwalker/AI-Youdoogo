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
from app.core.database import get_db
from app.models.system import SysUser
from app.platform.http_runtime import ok
from app.services import ai_provider_service as svc
from app.services import audit_service

router = APIRouter(prefix="/ai-providers", tags=["ai-provider"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


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


async def _sync_and_audit(
    db: DB, admin: SysUser, action: str, summary: str, card_id: uuid.UUID | None
) -> None:
    """卡片变更后：同步 factory + 落审计（detail 只记 id，不含密钥）。"""
    await svc.sync_to_factory(db)
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action=action,
        summary=summary, target_type="ai_provider", target_id=card_id,
    )


@router.get("")
async def list_providers(db: DB, _: Admin) -> dict:
    """卡片列表（密钥脱敏）。"""
    return ok(await svc.list_providers(db))


@router.post("")
async def create_provider(body: ProviderCreate, db: DB, admin: Admin) -> dict:
    """新建卡片。"""
    card = await svc.create(
        db, name=body.name, tier=body.tier,
        base_url=body.base_url, api_key=body.api_key, model=body.model,
    )
    await _sync_and_audit(db, admin, "ai_provider.create", f"新增 AI 卡片 {card.name}", card.id)
    return ok({"id": str(card.id), "name": card.name, "tier": card.tier})


@router.patch("/{provider_id}")
async def update_provider(
    provider_id: uuid.UUID, body: ProviderUpdate, db: DB, admin: Admin
) -> dict:
    """改卡片。"""
    card = await svc.update(
        db, provider_id, name=body.name, tier=body.tier,
        base_url=body.base_url, api_key=body.api_key, model=body.model,
    )
    await _sync_and_audit(db, admin, "ai_provider.update", f"修改 AI 卡片 {card.name}", card.id)
    return ok({"id": str(card.id), "name": card.name})


@router.delete("/{provider_id}")
async def delete_provider(provider_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """软删卡片。"""
    await svc.delete(db, provider_id)
    await _sync_and_audit(db, admin, "ai_provider.delete", "删除 AI 卡片", provider_id)
    return ok()


@router.post("/{provider_id}/test")
async def test_provider(provider_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """连通测试（落状态，不改注册）。"""
    return ok(await svc.test_provider(db, provider_id))


@router.post("/{provider_id}/primary")
async def set_primary(provider_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """设为该档位主用。"""
    card = await svc.set_primary(db, provider_id)
    await _sync_and_audit(db, admin, "ai_provider.primary", f"设主用 AI 卡片 {card.name}", card.id)
    return ok({"id": str(card.id)})


@router.post("/{provider_id}/toggle")
async def toggle_active(provider_id: uuid.UUID, body: ToggleBody, db: DB, admin: Admin) -> dict:
    """启用/禁用卡片。"""
    card = await svc.toggle_active(db, provider_id, body.active)
    verb = "启用" if body.active else "禁用"
    await _sync_and_audit(db, admin, "ai_provider.toggle", f"{verb} AI 卡片 {card.name}", card.id)
    return ok({"id": str(card.id), "is_active": card.is_active})


@router.post("/test-all")
async def test_all(db: DB, _: Admin) -> dict:
    """一键检测所有卡片（绿/红/灰）。"""
    return ok(await svc.test_all(db))
