"""统一权限判定（docs/13 §3 · F4b）：角色判定唯一权威 + 内容访问（scope ∪ grant）。

- check_role：所有角色门（require_roles）收敛到此，单一判定源。
- visible_kb_ids：内容访问统一入口，把 F2 的默认可见性（scope）与 F4b 的显式授权（grant）合并。
红线：本模块只判「访问权」，不判「生效权」——生效永远真人确认，且生效函数不进 agent tool 注册表。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.knowledge.scope import resolve_visible_kb_ids
from app.models.system import SysUser
from app.services import resource_grant_service


def check_role(user: SysUser, *roles: str) -> None:
    """角色门唯一判定：user.role_code 不在允许集则抛 403。"""
    if user.role_code not in roles:
        raise AppError("无权限执行此操作", code=403, status_code=403)


async def visible_kb_ids(db: AsyncSession, user: SysUser) -> list[uuid.UUID]:
    """请求用户可见知识库 id 集 = 默认可见性(scope) ∪ 显式授权(grant)；admin 全见。"""
    extra = await resource_grant_service.granted_kb_ids(db, user)
    return await resolve_visible_kb_ids(
        db,
        department_id=user.department_id,
        is_admin=user.role_code == "admin",
        extra_kb_ids=extra,
    )


async def can_read_resource(
    db: AsyncSession, user: SysUser, resource_type: str, resource_id: uuid.UUID
) -> bool:
    """某真人能否读某资源（默认 scope 或显式 grant）。预留给 data_source 等门控。"""
    if user.role_code == "admin":
        return True
    if resource_type == "knowledge_base":
        return resource_id in await visible_kb_ids(db, user)
    granted = await resource_grant_service.granted_resource_ids(db, user, resource_type)
    return resource_id in granted
