"""知识库集合管理接口（F2）：列表任意登录用户，增/删/改仅 admin。"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.foundations.knowledge.wiki_management.public import (
    create_knowledge_base,
    delete_knowledge_base,
    list_knowledge_bases,
    update_knowledge_base,
)
from app.core.database import get_db
from app.platform.http_runtime import ok
from app.schemas.knowledge import KnowledgeBaseCreate, KnowledgeBaseUpdate

router = APIRouter(prefix="/knowledge-bases", tags=["knowledge-base"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[object, Depends(require_roles("admin"))]


@router.get("")
async def list_kbs(db: DB, _: CurrentUser) -> dict:
    """全部知识库 + 各库文档数。"""
    return ok([item.to_dict() for item in await list_knowledge_bases(db)])


@router.post("")
async def create_kb(body: KnowledgeBaseCreate, db: DB, _: Admin) -> dict:
    """新建知识库（company/department/personal）。"""
    kb = await create_knowledge_base(
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
    kb = await update_knowledge_base(
        db,
        kb_id,
        name=body.name,
        is_confidential=body.is_confidential,
        description=body.description,
        is_active=body.is_active,
        department_id=body.department_id,
    )
    return ok({"id": str(kb.id), "name": kb.name})


@router.delete("/{kb_id}")
async def delete_kb(kb_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """删知识库（含文件时拒绝；公司公共库不可删）。"""
    await delete_knowledge_base(db, kb_id)
    return ok()
