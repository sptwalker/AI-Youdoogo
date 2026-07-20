"""飞书组织同步（I1，docs/18）：从飞书通讯录拉部门树 + 员工，幂等 upsert 到本地身份库。

范式复刻 ops_data.ingest_from_thinkingdata:resolve 凭证 → client 拉取 → 稳定键幂等 upsert。
- 部门:按 open_department_id 稳定键 upsert SysDepartment;物化 path/level 支持任意深度
  （放宽原 2 级硬限——飞书组织常 >2 级）。
- 员工:按 open_id 稳定键 upsert SysUser(中英文名/职务/手机/头像/部门)。
只读飞书、只写身份库，不触发任何决议;密钥走 sys_config 脱敏（红线）。手动 API 触发。
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError
from app.models.system import COMPANY, SysDepartment, SysUser

logger = logging.getLogger(__name__)


async def _company_root(db: AsyncSession) -> SysDepartment:
    """取公司根节点（同步的部门都挂在其下）。"""
    root = (
        await db.execute(select(SysDepartment).where(SysDepartment.node_type == COMPANY))
    ).scalar_one_or_none()
    if root is None:
        raise AppError("未初始化公司根节点，无法同步组织")
    return root


async def _dept_by_feishu(db: AsyncSession, open_id: str) -> SysDepartment | None:
    return (
        await db.execute(
            select(SysDepartment).where(
                SysDepartment.feishu_open_id == open_id, SysDepartment.is_delete.is_(False)
            )
        )
    ).scalar_one_or_none()


async def _user_by_feishu(db: AsyncSession, open_id: str) -> SysUser | None:
    return (
        await db.execute(
            select(SysUser).where(
                SysUser.feishu_open_id == open_id, SysUser.is_delete.is_(False)
            )
        )
    ).scalar_one_or_none()


def _sort_by_hierarchy(depts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按层级排序:父部门先于子部门（保证 upsert 时父已存在，可算 path）。

    飞书返回 parent_department_id;拓扑排序（无父或父不在集合内=顶层，先处理）。
    """
    by_id = {d.get("open_department_id"): d for d in depts if d.get("open_department_id")}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _visit(d: dict[str, Any]) -> None:
        oid = d.get("open_department_id")
        if not oid or oid in seen:
            return
        parent_fid = d.get("parent_department_id")
        parent = by_id.get(parent_fid) if parent_fid else None
        if parent is not None:
            _visit(parent)  # 父先入
        seen.add(oid)
        ordered.append(d)

    for d in depts:
        _visit(d)
    return ordered


async def _upsert_department(
    db: AsyncSession, fd: dict[str, Any], root: SysDepartment,
    fid_to_local: dict[str, SysDepartment],
) -> SysDepartment:
    """幂等 upsert 一个飞书部门。父部门已在 fid_to_local（拓扑序保证）或挂根。"""
    open_id = fd["open_department_id"]
    name = fd.get("name") or "未命名部门"
    parent_fid = fd.get("parent_department_id")
    parent = fid_to_local.get(parent_fid) if parent_fid else None
    if parent is None:
        parent = root  # 父不在本次集合 → 挂公司根

    dept = await _dept_by_feishu(db, open_id)
    if dept is None:
        dept = SysDepartment(
            name=name, code=f"fs_{open_id[:24]}", feishu_open_id=open_id,
            parent_id=parent.id, node_type="dept_l1",
        )
        db.add(dept)
        await db.flush()
    else:
        dept.name = name
        dept.parent_id = parent.id
    dept.level = parent.level + 1
    dept.path = f"{parent.path}{dept.id}/"
    return dept


async def _upsert_user(
    db: AsyncSession, fu: dict[str, Any], fid_to_local: dict[str, SysDepartment],
    root: SysDepartment,
) -> bool:
    """幂等 upsert 一个飞书员工。返回 True=新建。"""
    open_id = fu.get("open_id")
    if not open_id:
        return False
    name = fu.get("name") or "未命名"
    dept_ids = fu.get("department_ids") or []
    local_dept = next((fid_to_local[d] for d in dept_ids if d in fid_to_local), root)

    user = await _user_by_feishu(db, open_id)
    created = user is None
    if user is None:
        # 用户名用飞书 open_id 派生（唯一、稳定）；密码占位（真人走飞书 SSO 登录，I2）
        user = SysUser(
            username=f"fs_{open_id[:24]}", password_hash="!feishu-sso",
            feishu_open_id=open_id, role_code="member",
        )
        db.add(user)
    user.real_name = name
    user.en_name = fu.get("en_name") or ""
    user.title = (fu.get("job_title") or "") if isinstance(fu.get("job_title"), str) else ""
    user.mobile = fu.get("mobile") or ""
    user.avatar_url = ((fu.get("avatar") or {}).get("avatar_240") or "")
    user.department_id = local_dept.id
    return created


async def sync_from_feishu(db: AsyncSession) -> dict[str, int]:
    """从飞书通讯录全量同步组织 + 员工到本地身份库。幂等（稳定键 upsert）。

    Returns:
        {departments, users_created, users_updated}。
    Raises:
        AppError: 未配飞书凭证 / 未初始化公司根 / 飞书接口错误。
    """
    from app.integrations.feishu.client import FeishuAPIError, feishu_client

    root = await _company_root(db)
    try:
        raw_depts = await feishu_client.list_departments()
    except FeishuAPIError as exc:
        raise AppError(f"拉取飞书部门失败:{exc}", code=502, status_code=502) from exc

    fid_to_local: dict[str, SysDepartment] = {}
    for fd in _sort_by_hierarchy(raw_depts):
        dept = await _upsert_department(db, fd, root, fid_to_local)
        fid_to_local[fd["open_department_id"]] = dept
    await db.commit()

    users_created = users_updated = 0
    for open_id in list(fid_to_local.keys()):
        try:
            raw_users = await feishu_client.list_users_by_department(open_id)
        except FeishuAPIError:
            logger.warning("拉取部门 %s 员工失败，跳过", open_id, exc_info=True)
            continue
        for fu in raw_users:
            if await _upsert_user(db, fu, fid_to_local, root):
                users_created += 1
            else:
                users_updated += 1
    await db.commit()
    return {
        "departments": len(fid_to_local),
        "users_created": users_created,
        "users_updated": users_updated,
    }


async def list_feishu_users(db: AsyncSession, *, limit: int = 500) -> list[dict[str, Any]]:
    """列出已同步的飞书员工（供群聊选人等，I4 复用）。"""
    stmt = (
        select(SysUser)
        .where(SysUser.feishu_open_id.is_not(None), SysUser.is_delete.is_(False))
        .order_by(SysUser.real_name)
        .limit(limit)
    )
    return [
        {
            "id": str(u.id), "real_name": u.real_name, "en_name": u.en_name,
            "title": u.title, "department_id": str(u.department_id) if u.department_id else None,
            "avatar_url": u.avatar_url,
        }
        for u in (await db.execute(stmt)).scalars()
    ]
