"""知识库集合管理接口（F2）：列表任意登录用户，增/删/改仅 admin。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import ok
from app.models.system import SysUser
from app.schemas.knowledge import KnowledgeBaseCreate, KnowledgeBaseUpdate
from app.services import knowledge_base_service as kb_svc

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-base"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


@router.get("")
async def list_kbs(db: DB, _: CurrentUser) -> dict:
    """全部知识库 + 各库文档数。"""
    return ok(await kb_svc.list_kbs(db))


@router.post("")
async def create_kb(body: KnowledgeBaseCreate, db: DB, _: Admin) -> dict:
    """新建知识库（company/department/personal）。"""
    kb = await kb_svc.create_kb(
        db,
        name=body.name,
        scope=body.scope,
        code=body.code,
        department_id=body.department_id,
        owner_agent_id=body.owner_agent_id,
        is_confidential=body.is_confidential,
        description=body.description,
    )
    return ok({"id": str(kb.id), "name": kb.name, "code": kb.code})


@router.patch("/{kb_id}")
async def update_kb(kb_id: uuid.UUID, body: KnowledgeBaseUpdate, db: DB, _: Admin) -> dict:
    """改知识库名/机密标记/描述/启用。"""
    kb = await kb_svc.update_kb(
        db, kb_id,
        name=body.name, is_confidential=body.is_confidential,
        description=body.description, is_active=body.is_active,
    )
    return ok({"id": str(kb.id), "name": kb.name})


@router.delete("/{kb_id}")
async def delete_kb(kb_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """删知识库（含文件时拒绝；公司公共库不可删）。"""
    await kb_svc.delete_kb(db, kb_id)
    return ok()
