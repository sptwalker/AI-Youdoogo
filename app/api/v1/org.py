"""组织架构接口（F1，仅 admin）：部门树 CRUD + 真人主管 + 员工 + 一键初始化骨架。

管理员搭公司骨架的入口。读（树/员工）任意登录用户；改（建/删部门、设主管、员工、初始化）仅 admin。
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.core.database import get_db
from app.core.exceptions import ok
from app.models.system import SysUser
from app.schemas.org import (
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    NodeCreate,
    NodeOut,
    NodeUpdate,
    SupervisorSet,
)
from app.services import agent_role_service, org_service, org_template

router = APIRouter(prefix="/org", tags=["org"])

DB = Annotated[AsyncSession, Depends(get_db)]
Admin = Annotated[SysUser, Depends(require_roles("admin"))]


def _emp(role: object) -> dict:
    return EmployeeOut.model_validate(role).model_dump(mode="json")


@router.get("/tree")
async def get_tree(db: DB, _: CurrentUser) -> dict:
    """公司组织树（嵌套）。"""
    return ok(await org_service.get_tree(db))


@router.post("/init-template")
async def init_template(db: DB, admin: Admin) -> dict:
    """一键按模板初始化公司骨架（幂等）：公司根 + 8 部门 + 7 高管 + 8 总监；根主管=CEO。"""
    return ok(await org_template.seed_org_template(db, ceo_user_id=admin.id))


@router.post("/nodes")
async def create_node(body: NodeCreate, db: DB, _: Admin) -> dict:
    """新建部门（一级/二级，层级≤2）。"""
    node = await org_service.create_node(
        db, name=body.name, parent_id=body.parent_id, code=body.code
    )
    return ok(NodeOut.model_validate(node).model_dump(mode="json"))


@router.patch("/nodes/{dept_id}")
async def update_node(dept_id: uuid.UUID, body: NodeUpdate, db: DB, _: Admin) -> dict:
    """改部门名/排序。"""
    node = await org_service.update_node(db, dept_id, name=body.name, sort_order=body.sort_order)
    return ok(NodeOut.model_validate(node).model_dump(mode="json"))


@router.delete("/nodes/{dept_id}")
async def delete_node(dept_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """删部门（有子部门/员工时拒绝）。"""
    await org_service.delete_node(db, dept_id)
    return ok()


@router.put("/nodes/{dept_id}/supervisor")
async def set_supervisor(dept_id: uuid.UUID, body: SupervisorSet, db: DB, _: Admin) -> dict:
    """设置部门真人主管（跨部门协作确认/复核人）。"""
    node = await org_service.set_supervisor(db, dept_id, body.supervisor_user_id)
    return ok(NodeOut.model_validate(node).model_dump(mode="json"))


@router.get("/nodes/{dept_id}/employees")
async def list_employees(dept_id: uuid.UUID, db: DB, _: CurrentUser) -> dict:
    """部门下的智能体员工。"""
    emps = await org_service.list_employees(db, dept_id)
    return ok([_emp(e) for e in emps])


@router.post("/nodes/{dept_id}/employees")
async def create_employee(dept_id: uuid.UUID, body: EmployeeCreate, db: DB, _: Admin) -> dict:
    """在部门下新增智能体员工。"""
    await org_service.get_node(db, dept_id)  # 校验部门存在
    role = await agent_role_service.create_agent_role(
        db,
        name=body.name,
        prompt_template=body.prompt_template,
        duty=body.duty,
        model_role=body.model_role,
        department_id=dept_id,
        tier=body.tier,
        title=body.title,
        report_to_id=body.report_to_id,
    )
    return ok(_emp(role))


@router.patch("/employees/{emp_id}")
async def update_employee(emp_id: uuid.UUID, body: EmployeeUpdate, db: DB, _: Admin) -> dict:
    """更新智能体员工。"""
    role = await agent_role_service.update_agent_role(
        db, emp_id,
        prompt_template=body.prompt_template, duty=body.duty, model_role=body.model_role,
        is_active=body.is_active, title=body.title, tier=body.tier,
        report_to_id=body.report_to_id, department_id=body.department_id,
    )
    return ok(_emp(role))


@router.delete("/employees/{emp_id}")
async def delete_employee(emp_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """删除智能体员工（骨架种子不可删）。"""
    await agent_role_service.delete_agent_role(db, emp_id)
    return ok()
