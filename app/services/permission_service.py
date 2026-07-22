"""统一权限判定（docs/13 §3 · F4b）：角色判定唯一权威 + 内容访问（scope ∪ grant）。

- check_role：所有角色门（require_roles）收敛到此，单一判定源。
- visible_kb_ids：内容访问统一入口，把 F2 的默认可见性（scope）与 F4b 的显式授权（grant）合并。
红线：本模块只判「访问权」，不判「生效权」——生效永远真人确认，且生效函数不进 agent tool 注册表。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.shared_kernel import PermissionDenied, ResourceNotFound
from app.knowledge.scope import resolve_visible_kb_ids
from app.models.system import SysUser
from app.services import resource_grant_service

# 管理层角色：对业务卡（提案/任务/会议）有全局监督可见性（跨部门读，按需审计）。
_PRIVILEGED = ("admin", "executive")


def check_role(user: SysUser, *roles: str) -> None:
    """角色门唯一判定：user.role_code 不在允许集则抛 403。"""
    if user.role_code not in roles:
        raise PermissionDenied("无权限执行此操作")


def is_privileged(user: SysUser) -> bool:
    """管理层（admin/executive）：业务卡全局可见（监督）。"""
    return user.role_code in _PRIVILEGED


def can_see_row(
    user: SysUser,
    *,
    creator_id: uuid.UUID | None,
    department_id: uuid.UUID | None = None,
    assignee_user_id: uuid.UUID | None = None,
) -> bool:
    """行级可见性判定（H1.2，docs/16 P0-2）：管理层全见；普通员工见 本人创建 ∪ 本部门 ∪ 派给己。"""
    if is_privileged(user):
        return True
    if creator_id is not None and creator_id == user.id:
        return True
    if assignee_user_id is not None and assignee_user_id == user.id:
        return True
    return department_id is not None and department_id == user.department_id


def assert_can_see(
    user: SysUser,
    *,
    creator_id: uuid.UUID | None,
    department_id: uuid.UUID | None = None,
    assignee_user_id: uuid.UUID | None = None,
) -> None:
    """行级可见性守卫：不可见抛 404（不泄露资源存在性）。"""
    if not can_see_row(
        user, creator_id=creator_id, department_id=department_id,
        assignee_user_id=assignee_user_id,
    ):
        raise ResourceNotFound("资源不存在")


def row_filter(model: Any, user: SysUser) -> Any | None:
    """列表查询的行级可见性 where 子句。管理层返回 None（不加过滤=全见）。

    普通员工：creator_id=本人 OR department_id=本部门 OR assignee_user_id=本人（若模型有该列）。
    """
    if is_privileged(user):
        return None
    conds = [model.creator_id == user.id]
    if user.department_id is not None and hasattr(model, "department_id"):
        conds.append(model.department_id == user.department_id)
    if hasattr(model, "assignee_user_id"):
        conds.append(model.assignee_user_id == user.id)
    return or_(*conds)


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
