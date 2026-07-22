"""飞书组织同步单测（I1，docs/18）:层级排序纯函数 + sync 幂等（打桩飞书 client）。"""

from collections.abc import AsyncGenerator
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.models import Base
from app.models.system import COMPANY, SysDepartment, SysUser
from app.services import org_sync_service


@pytest.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _root(db: AsyncSession) -> SysDepartment:
    root = SysDepartment(name="创想悦动", code="company", node_type=COMPANY, level=0, path="/root/")
    db.add(root)
    await db.commit()
    await db.refresh(root)
    return root


# ── _sort_by_hierarchy 纯函数 ───────────────────────────
def test_sort_parent_before_child() -> None:
    depts = [
        {"open_department_id": "c", "parent_department_id": "b", "name": "孙"},
        {"open_department_id": "a", "parent_department_id": "0", "name": "父"},
        {"open_department_id": "b", "parent_department_id": "a", "name": "子"},
    ]
    ordered = org_sync_service._sort_by_hierarchy(depts)
    ids = [d["open_department_id"] for d in ordered]
    assert ids.index("a") < ids.index("b") < ids.index("c")  # 父→子→孙


def test_sort_handles_missing_parent() -> None:
    """父不在集合内（顶层挂根）→ 不死循环，正常返回。"""
    depts = [{"open_department_id": "x", "parent_department_id": "外部根", "name": "x"}]
    assert len(org_sync_service._sort_by_hierarchy(depts)) == 1


# ── sync_from_feishu（打桩 client）──────────────────────
def _stub_client(
    monkeypatch: pytest.MonkeyPatch,
    depts: list[dict[str, Any]],
    users_by_dept: dict[str, list[dict[str, Any]]],
) -> None:
    from app.integrations.feishu import client as fc

    async def _list_depts(*a: Any, **k: Any) -> list[dict[str, Any]]:
        return depts

    async def _list_users(department_id: str, **k: Any) -> list[dict[str, Any]]:
        return users_by_dept.get(department_id, [])

    monkeypatch.setattr(fc.feishu_client, "list_departments", _list_depts)
    monkeypatch.setattr(fc.feishu_client, "list_users_by_department", _list_users)


async def test_sync_builds_dept_tree_and_users(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _root(db)
    depts = [
        {"open_department_id": "d1", "parent_department_id": "0", "name": "技术部"},
        {"open_department_id": "d2", "parent_department_id": "d1", "name": "后端组"},  # 3级
    ]
    users = {
        "d1": [{"open_id": "u1", "name": "张三", "en_name": "San Zhang",
                "job_title": "总监", "mobile": "13800000000", "department_ids": ["d1"]}],
        "d2": [{"open_id": "u2", "name": "李四", "department_ids": ["d2"]}],
    }
    _stub_client(monkeypatch, depts, users)
    res = await org_sync_service.sync_from_feishu(db)
    assert res["departments"] == 2 and res["users_created"] == 2

    # 3 级部门被接受（放宽 2 级硬限）
    d2 = (await db.execute(
        select(SysDepartment).where(SysDepartment.feishu_open_id == "d2")
    )).scalar_one()
    assert d2.level == 2  # 根(0)→技术部(1)→后端组(2)
    # 员工身份齐全
    u1 = (await db.execute(
        select(SysUser).where(SysUser.feishu_open_id == "u1")
    )).scalar_one()
    assert u1.real_name == "张三" and u1.en_name == "San Zhang" and u1.title == "总监"


async def test_sync_idempotent(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """重复同步不造重复（open_id 稳定键 upsert）。"""
    await _root(db)
    depts = [{"open_department_id": "d1", "parent_department_id": "0", "name": "技术部"}]
    users = {"d1": [{"open_id": "u1", "name": "张三", "department_ids": ["d1"]}]}
    _stub_client(monkeypatch, depts, users)

    await org_sync_service.sync_from_feishu(db)
    res2 = await org_sync_service.sync_from_feishu(db)
    assert res2["users_created"] == 0 and res2["users_updated"] == 1  # 第二次是更新
    # 部门/用户各只 1 条（未重复）
    ndept = (await db.execute(
        select(func.count()).select_from(SysDepartment).where(
            SysDepartment.feishu_open_id.is_not(None)
        )
    )).scalar_one()
    nuser = (await db.execute(
        select(func.count()).select_from(SysUser).where(SysUser.feishu_open_id.is_not(None))
    )).scalar_one()
    assert ndept == 1 and nuser == 1


async def test_sync_requires_root(db: AsyncSession, monkeypatch: pytest.MonkeyPatch) -> None:
    """未初始化公司根 → 报错。"""
    from app.contexts.shared_kernel import ApplicationError

    _stub_client(monkeypatch, [], {})
    with pytest.raises(ApplicationError, match="根节点"):
        await org_sync_service.sync_from_feishu(db)


async def test_sync_updates_existing_user(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已同步员工改了职务 → 更新而非新建。"""
    await _root(db)
    depts = [{"open_department_id": "d1", "parent_department_id": "0", "name": "技术部"}]
    _stub_client(monkeypatch, depts, {"d1": [
        {"open_id": "u1", "name": "张三", "job_title": "工程师", "department_ids": ["d1"]}
    ]})
    await org_sync_service.sync_from_feishu(db)
    # 改职务再同步
    _stub_client(monkeypatch, depts, {"d1": [
        {"open_id": "u1", "name": "张三", "job_title": "高级工程师", "department_ids": ["d1"]}
    ]})
    await org_sync_service.sync_from_feishu(db)
    u = (await db.execute(select(SysUser).where(SysUser.feishu_open_id == "u1"))).scalar_one()
    assert u.title == "高级工程师"
