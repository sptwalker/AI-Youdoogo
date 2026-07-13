"""知识库可见范围推导（docs/13 契约② · F2 唯一 P0 回归点）。

默认全公司可见 + 机密标记（减法隔离）：
  可见库 = 所有非机密 company/department 库（全员）
         ∪ 归属"本部门及其祖先链"的机密库
         ∪ 本人 personal 库（owner）
         ∪ admin 全部可见（跨部门检索由调用方落审计）
resource_grant 显式授权部分留 F4 接入（本函数签名预留 extra_kb_ids）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import SCOPE_PERSONAL, KnowledgeBase
from app.models.system import SysDepartment


async def _dept_path(db: AsyncSession, department_id: uuid.UUID | None) -> str:
    """取部门物化路径（用于祖先链判断）；无部门返回空串。"""
    if department_id is None:
        return ""
    dept = await db.get(SysDepartment, department_id)
    return dept.path if dept and not dept.is_delete else ""


def _ancestor_ids(path: str) -> list[uuid.UUID]:
    """从物化路径 /{root}/{l1}/{l2}/ 解析出本节点及祖先链的 id 列表。"""
    return [uuid.UUID(seg) for seg in path.strip("/").split("/") if seg]


async def resolve_visible_kb_ids(
    db: AsyncSession,
    *,
    department_id: uuid.UUID | None,
    owner_agent_id: uuid.UUID | None = None,
    is_admin: bool = False,
    extra_kb_ids: list[uuid.UUID] | None = None,
) -> list[uuid.UUID]:
    """算出某身份（真人或 AI 员工）可见的知识库 id 集。

    Args:
        department_id: 该身份所属部门（真人 sys_user.department_id / AI agent_role.department_id）。
        owner_agent_id: 若为某 AI 员工本人，其 personal 库归属 id（=该 agent 自身 id）。
        is_admin: 管理员（CEO/最高权限）全库可见。
        extra_kb_ids: 显式授权的库（F4 resource_grant，本阶段调用方可传空）。
    """
    if is_admin:
        stmt = select(KnowledgeBase.id).where(
            KnowledgeBase.is_active.is_(True), KnowledgeBase.is_delete.is_(False)
        )
        return list((await db.execute(stmt)).scalars())

    path = await _dept_path(db, department_id)
    ancestors = _ancestor_ids(path)

    # 1) 所有非机密 company/department 库（全员默认可见）
    public_cond = KnowledgeBase.is_confidential.is_(False)
    # 2) 归属本部门及祖先链的机密库
    conf_cond = KnowledgeBase.is_confidential.is_(True) & (
        KnowledgeBase.department_id.in_(ancestors) if ancestors else false()
    )
    # 3) 本人 personal 库
    personal_cond = (
        (KnowledgeBase.scope == SCOPE_PERSONAL) & (KnowledgeBase.owner_agent_id == owner_agent_id)
        if owner_agent_id is not None
        else false()
    )

    stmt = select(KnowledgeBase.id).where(
        KnowledgeBase.is_active.is_(True),
        KnowledgeBase.is_delete.is_(False),
        # personal 库即便非机密也不该全员可见 → 排除他人 personal
        or_(
            (public_cond & (KnowledgeBase.scope != SCOPE_PERSONAL)),
            conf_cond,
            personal_cond,
        ),
    )
    ids = list((await db.execute(stmt)).scalars())
    if extra_kb_ids:
        ids = list({*ids, *extra_kb_ids})
    return ids


def _demo() -> None:
    """路径解析自检（无 DB）。"""
    root = uuid.uuid4()
    l1 = uuid.uuid4()
    p = f"/{root}/{l1}/"
    assert _ancestor_ids(p) == [root, l1], _ancestor_ids(p)
    assert _ancestor_ids("") == []
    print("scope._demo ok")


if __name__ == "__main__":
    _demo()
