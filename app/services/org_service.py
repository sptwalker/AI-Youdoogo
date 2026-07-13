"""组织架构业务逻辑（F1）：部门树 CRUD + 真人主管 + 部门员工列表。

层级 ≤2（公司根 level0 / 一级 level1 / 二级 level2）；物化路径 path 维护子树查询。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.agent import AgentRole
from app.models.discussion import DiscussionChannel
from app.models.system import COMPANY, DEPT_L1, DEPT_L2, SysDepartment, SysUser

_NODE_TYPE_BY_LEVEL = {0: COMPANY, 1: DEPT_L1, 2: DEPT_L2}


async def get_node(db: AsyncSession, dept_id: uuid.UUID) -> SysDepartment:
    dept = await db.get(SysDepartment, dept_id)
    if dept is None or dept.is_delete:
        raise AppError("部门不存在", code=404, status_code=404)
    return dept


async def _all_nodes(db: AsyncSession) -> list[SysDepartment]:
    stmt = (
        select(SysDepartment)
        .where(SysDepartment.is_delete.is_(False))
        .order_by(SysDepartment.level, SysDepartment.sort_order, SysDepartment.create_time)
    )
    return list((await db.execute(stmt)).scalars())


async def get_tree(db: AsyncSession) -> list[dict[str, Any]]:
    """返回嵌套部门树（根在最外层），每节点带 AI 员工数 employee_count。"""
    nodes = await _all_nodes(db)
    # 各部门在职 AI 员工数（一次 group by）
    counts: dict[uuid.UUID, int] = {
        dept_id: int(n)
        for dept_id, n in (
            await db.execute(
                select(AgentRole.department_id, func.count())
                .where(AgentRole.is_delete.is_(False), AgentRole.department_id.is_not(None))
                .group_by(AgentRole.department_id)
            )
        ).all()
    }
    by_id: dict[uuid.UUID, dict[str, Any]] = {
        n.id: {
            "id": str(n.id), "name": n.name, "code": n.code, "node_type": n.node_type,
            "level": n.level, "parent_id": str(n.parent_id) if n.parent_id else None,
            "supervisor_user_id": str(n.supervisor_user_id) if n.supervisor_user_id else None,
            "employee_count": counts.get(n.id, 0),
            "children": [],
        }
        for n in nodes
    }
    roots: list[dict[str, Any]] = []
    for n in nodes:
        node = by_id[n.id]
        if n.parent_id and n.parent_id in by_id:
            by_id[n.parent_id]["children"].append(node)
        else:
            roots.append(node)
    return roots


async def create_node(
    db: AsyncSession, *, name: str, parent_id: uuid.UUID, code: str | None = None
) -> SysDepartment:
    """在 parent 下建子部门（level=parent+1，≤2）。code 缺省自动生成。"""
    parent = await get_node(db, parent_id)
    level = parent.level + 1
    if level > 2:
        raise AppError("部门层级最多两级（一级/二级），不能再往下建")
    node = SysDepartment(
        name=name,
        code=code or f"dept_{uuid.uuid4().hex[:8]}",
        parent_id=parent.id,
        node_type=_NODE_TYPE_BY_LEVEL[level],
        level=level,
    )
    db.add(node)
    await db.flush()
    node.path = f"{parent.path}{node.id}/"
    # F3'：部门自动种子一个讨论频道
    db.add(DiscussionChannel(name=f"{name}讨论区", department_id=node.id))
    await db.commit()
    await db.refresh(node)
    return node


async def update_node(
    db: AsyncSession, dept_id: uuid.UUID, *, name: str | None = None, sort_order: int | None = None
) -> SysDepartment:
    node = await get_node(db, dept_id)
    if node.node_type == COMPANY and name is not None:
        raise AppError("公司根节点名称不可改（如需改公司名走系统配置）")
    if name is not None:
        node.name = name
    if sort_order is not None:
        node.sort_order = sort_order
    await db.commit()
    await db.refresh(node)
    return node


async def delete_node(db: AsyncSession, dept_id: uuid.UUID) -> None:
    """软删部门。有子部门或在职员工时拒绝（先清空再删）。"""
    node = await get_node(db, dept_id)
    if node.node_type == COMPANY:
        raise AppError("公司根节点不可删除")
    children = (
        await db.execute(
            select(SysDepartment.id).where(
                SysDepartment.parent_id == dept_id, SysDepartment.is_delete.is_(False)
            )
        )
    ).first()
    if children:
        raise AppError("该部门下还有子部门，请先移除子部门")
    emps = (
        await db.execute(
            select(AgentRole.id).where(
                AgentRole.department_id == dept_id, AgentRole.is_delete.is_(False)
            )
        )
    ).first()
    if emps:
        raise AppError("该部门下还有智能体员工，请先移除或转移")
    node.is_delete = True
    await db.commit()


async def set_supervisor(
    db: AsyncSession, dept_id: uuid.UUID, supervisor_user_id: uuid.UUID | None
) -> SysDepartment:
    """设置部门真人主管（跨部门协作确认/复核人）。"""
    node = await get_node(db, dept_id)
    if supervisor_user_id is not None:
        user = await db.get(SysUser, supervisor_user_id)
        if user is None or user.is_delete:
            raise AppError("指定的主管用户不存在")
    node.supervisor_user_id = supervisor_user_id
    await db.commit()
    await db.refresh(node)
    return node


async def list_employees(db: AsyncSession, dept_id: uuid.UUID) -> list[AgentRole]:
    """列出某部门的智能体员工（按层级、创建时间）。"""
    stmt = (
        select(AgentRole)
        .where(AgentRole.department_id == dept_id, AgentRole.is_delete.is_(False))
        .order_by(AgentRole.tier, AgentRole.create_time)
    )
    return list((await db.execute(stmt)).scalars())
