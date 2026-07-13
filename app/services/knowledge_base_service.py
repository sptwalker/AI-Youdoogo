"""知识库集合管理（F2）：建库/列表/改/删。scope + 机密标记（契约②）。"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.knowledge import (
    SCOPE_COMPANY,
    SCOPE_DEPARTMENT,
    SCOPE_PERSONAL,
    KnowledgeBase,
    KnowledgeFile,
)

VALID_SCOPES = (SCOPE_COMPANY, SCOPE_DEPARTMENT, SCOPE_PERSONAL)


async def get_kb(db: AsyncSession, kb_id: uuid.UUID) -> KnowledgeBase:
    kb = await db.get(KnowledgeBase, kb_id)
    if kb is None or kb.is_delete:
        raise AppError("知识库不存在", code=404, status_code=404)
    return kb


async def get_default_kb(db: AsyncSession) -> KnowledgeBase:
    """公司公共库（入库缺省目标）。"""
    stmt = select(KnowledgeBase).where(
        KnowledgeBase.is_default.is_(True), KnowledgeBase.is_delete.is_(False)
    )
    kb = (await db.execute(stmt)).scalar_one_or_none()
    if kb is None:
        raise AppError("未找到公司公共知识库，请先执行数据库迁移")
    return kb


async def create_kb(
    db: AsyncSession,
    *,
    name: str,
    scope: str,
    code: str | None = None,
    department_id: uuid.UUID | None = None,
    owner_agent_id: uuid.UUID | None = None,
    is_confidential: bool = False,
    description: str | None = None,
) -> KnowledgeBase:
    """新建知识库。department scope 需 department_id；personal scope 需 owner_agent_id。"""
    if scope not in VALID_SCOPES:
        raise AppError(f"scope 仅支持 {'/'.join(VALID_SCOPES)}")
    if scope == SCOPE_DEPARTMENT and department_id is None:
        raise AppError("部门知识库需指定所属部门")
    if scope == SCOPE_PERSONAL and owner_agent_id is None:
        raise AppError("个人知识区需指定归属的智能体")
    kb = KnowledgeBase(
        name=name,
        code=code or f"kb_{uuid.uuid4().hex[:8]}",
        scope=scope,
        department_id=department_id if scope == SCOPE_DEPARTMENT else None,
        owner_agent_id=owner_agent_id if scope == SCOPE_PERSONAL else None,
        is_confidential=is_confidential,
        description=description,
    )
    db.add(kb)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise AppError("知识库编码已存在", code=409, status_code=409) from exc
    await db.refresh(kb)
    return kb


async def update_kb(
    db: AsyncSession,
    kb_id: uuid.UUID,
    *,
    name: str | None = None,
    is_confidential: bool | None = None,
    description: str | None = None,
    is_active: bool | None = None,
) -> KnowledgeBase:
    kb = await get_kb(db, kb_id)
    if name is not None:
        kb.name = name
    if is_confidential is not None:
        kb.is_confidential = is_confidential
    if description is not None:
        kb.description = description
    if is_active is not None:
        kb.is_active = is_active
    await db.commit()
    await db.refresh(kb)
    return kb


async def delete_kb(db: AsyncSession, kb_id: uuid.UUID) -> None:
    """软删知识库。含文件时拒绝（先清空文件）；公司公共库不可删。"""
    kb = await get_kb(db, kb_id)
    if kb.is_default:
        raise AppError("公司公共知识库不可删除")
    n = (
        await db.execute(
            select(func.count())
            .select_from(KnowledgeFile)
            .where(
                KnowledgeFile.knowledge_base_id == kb_id, KnowledgeFile.is_delete.is_(False)
            )
        )
    ).scalar_one()
    if n:
        raise AppError(f"该知识库下还有 {n} 个文档，请先删除文档")
    kb.is_delete = True
    await db.commit()


async def list_kbs(db: AsyncSession) -> list[dict[str, Any]]:
    """全部知识库 + 各库文档数。"""
    counts: dict[uuid.UUID, int] = {
        kb_id: int(c)
        for kb_id, c in (
            await db.execute(
                select(KnowledgeFile.knowledge_base_id, func.count())
                .where(KnowledgeFile.is_delete.is_(False))
                .group_by(KnowledgeFile.knowledge_base_id)
            )
        ).all()
    }
    stmt = (
        select(KnowledgeBase)
        .where(KnowledgeBase.is_delete.is_(False))
        .order_by(KnowledgeBase.is_default.desc(), KnowledgeBase.create_time)
    )
    kbs = list((await db.execute(stmt)).scalars())
    return [
        {
            "id": str(kb.id), "name": kb.name, "code": kb.code, "scope": kb.scope,
            "department_id": str(kb.department_id) if kb.department_id else None,
            "owner_agent_id": str(kb.owner_agent_id) if kb.owner_agent_id else None,
            "is_confidential": kb.is_confidential, "is_default": kb.is_default,
            "is_active": kb.is_active, "description": kb.description,
            "file_count": counts.get(kb.id, 0),
        }
        for kb in kbs
    ]
