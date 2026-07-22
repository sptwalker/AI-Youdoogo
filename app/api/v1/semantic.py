"""业务术语字典接口（统一语义层，docs/15 §4.2，仅 admin 维护）。

术语字典是全公司统一口径的参考数据，只提供口径/别名，不触发任何业务决议。
读（列表）任意登录用户；写（增删改）仅 admin，落审计。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.models.system import SysUser
from app.platform.http_runtime import ok
from app.services import audit_service, semantic_service

router = APIRouter(prefix="/semantic-terms", tags=["semantic"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


class TermCreate(BaseModel):
    """新建术语。规范名必填且唯一。"""

    canonical_name: str = Field(min_length=1, max_length=128)
    aliases: list[str] = Field(default_factory=list)
    term_type: str = Field(default="metric", pattern="^(metric|dimension|entity)$")
    definition: str | None = None
    linked_view: str | None = Field(default=None, max_length=64)
    sql_template: str | None = None
    kb_refs: list[str] = Field(default_factory=list)
    department_id: uuid.UUID | None = None


class TermUpdate(BaseModel):
    """改术语（仅传需改字段）。"""

    canonical_name: str | None = Field(default=None, min_length=1, max_length=128)
    aliases: list[str] | None = None
    term_type: str | None = Field(default=None, pattern="^(metric|dimension|entity)$")
    definition: str | None = None
    linked_view: str | None = Field(default=None, max_length=64)
    sql_template: str | None = None
    kb_refs: list[str] | None = None
    department_id: uuid.UUID | None = None


@router.get("")
async def list_terms(db: DB, _: CurrentUser) -> dict:
    """术语字典列表（未删除，按类型+规范名）。"""
    return ok(await semantic_service.list_terms(db))


@router.post("")
async def create_term(body: TermCreate, db: DB, admin: Admin) -> dict:
    """新建术语 → 落审计。"""
    term = await semantic_service.create_term(db, body.model_dump())
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action="semantic.create",
        summary=f"新建术语：{body.canonical_name}",
        target_type="semantic_term", target_id=uuid.UUID(term["id"]),
    )
    return ok(term)


@router.put("/{term_id}")
async def update_term(term_id: uuid.UUID, body: TermUpdate, db: DB, admin: Admin) -> dict:
    """改术语（仅传字段）→ 落审计。"""
    term = await semantic_service.update_term(
        db, term_id, body.model_dump(exclude_unset=True)
    )
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action="semantic.update",
        summary=f"改术语：{term['canonical_name']}",
        target_type="semantic_term", target_id=term_id,
    )
    return ok(term)


@router.delete("/{term_id}")
async def delete_term(term_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """删术语（软删）→ 落审计。"""
    await semantic_service.delete_term(db, term_id)
    await audit_service.audit(
        db, actor_id=admin.id, actor_role=admin.role_code, action="semantic.delete",
        summary="删除术语", target_type="semantic_term", target_id=term_id,
    )
    return ok()
