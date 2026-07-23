"""组织架构接口（F1，仅 admin）：部门树 CRUD + 真人主管 + 员工 + 一键初始化骨架。

管理员搭公司骨架的入口。读（树/员工）任意登录用户；改（建/删部门、设主管、员工、初始化）仅 admin。
"""

import uuid
from typing import Annotated, Protocol

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, require_roles
from app.contexts.foundations.governance.audit_trail.public import (
    AppendAuditRecordCommand,
    append_audit_record,
)
from app.contexts.foundations.organization_structure.contracts import DepartmentSnapshot
from app.contexts.foundations.organization_structure.entrypoints import operations
from app.contexts.foundations.organization_structure.entrypoints.legacy import (
    department_view,
    tree_view,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.entrypoints.legacy import (
    legacy_view as expert_view,
)
from app.core.database import get_db
from app.platform.http_runtime import ok
from app.schemas.org import (
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    NodeCreate,
    NodeOut,
    NodeUpdate,
    SupervisorSet,
)

router = APIRouter(prefix="/org", tags=["org"])

DB = Annotated[AsyncSession, Depends(get_db)]


class RequestUser(Protocol):
    id: uuid.UUID
    role_code: str


Admin = Annotated[RequestUser, Depends(require_roles("admin"))]


def _node(snapshot: DepartmentSnapshot) -> dict:
    return NodeOut.model_validate(department_view(snapshot)).model_dump(mode="json")


def _emp(snapshot: ExpertRosterSnapshot) -> dict:
    return EmployeeOut.model_validate(expert_view(snapshot)).model_dump(mode="json")


@router.get("/tree")
async def get_tree(db: DB, _: CurrentUser) -> dict:
    """公司组织树（嵌套）。"""
    return ok(tree_view(await operations.get_snapshot(db)))


@router.post("/sync-feishu")
async def sync_feishu(db: DB, admin: Admin) -> dict:
    """从飞书通讯录同步组织架构 + 员工身份（I1，docs/18）。幂等。"""
    result = await operations.sync_from_feishu(db)
    await append_audit_record(
        db,
        AppendAuditRecordCommand(
            actor_id=admin.id,
            actor_role=admin.role_code,
            action="org.sync_feishu",
            summary=f"飞书组织同步：{result['departments']}部门/新增{result['users_created']}人",
        ),
    )
    return ok(result)


@router.post("/init-template")
async def init_template(db: DB, admin: Admin) -> dict:
    """一键按模板初始化公司骨架（幂等）：公司根 + 8 部门 + 7 高管 + 8 总监；根主管=CEO。"""
    result = await operations.seed_org_template(db, ceo_user_id=admin.id)
    await append_audit_record(
        db,
        AppendAuditRecordCommand(
            actor_id=admin.id,
            actor_role=admin.role_code,
            action="org.init_template",
            summary="一键初始化公司骨架",
            detail=result,
        ),
    )
    return ok(result)


@router.post("/nodes")
async def create_node(body: NodeCreate, db: DB, admin: Admin) -> dict:
    """新建部门（一级/二级，层级≤2）。"""
    node = await operations.create_department(
        db, name=body.name, parent_id=body.parent_id, code=body.code
    )
    await append_audit_record(
        db,
        AppendAuditRecordCommand(
            actor_id=admin.id,
            actor_role=admin.role_code,
            action="org.node.create",
            summary=f"新建部门 {node.name}",
            target_type="sys_department",
            target_id=node.department_id,
        ),
    )
    return ok(_node(node))


@router.patch("/nodes/{dept_id}")
async def update_node(dept_id: uuid.UUID, body: NodeUpdate, db: DB, _: Admin) -> dict:
    """改部门名/排序。"""
    node = await operations.update_department(
        db,
        department_id=dept_id,
        name=body.name,
        sort_order=body.sort_order,
    )
    return ok(_node(node))


@router.delete("/nodes/{dept_id}")
async def delete_node(dept_id: uuid.UUID, db: DB, admin: Admin) -> dict:
    """删部门（有子部门/员工时拒绝）。"""
    await operations.delete_department(db, dept_id)
    await append_audit_record(
        db,
        AppendAuditRecordCommand(
            actor_id=admin.id,
            actor_role=admin.role_code,
            action="org.node.delete",
            summary="删除部门",
            target_type="sys_department",
            target_id=dept_id,
        ),
    )
    return ok()


@router.put("/nodes/{dept_id}/supervisor")
async def set_supervisor(dept_id: uuid.UUID, body: SupervisorSet, db: DB, admin: Admin) -> dict:
    """设置部门真人主管（跨部门协作确认/复核人）。"""
    node = await operations.set_supervisor(
        db,
        department_id=dept_id,
        supervisor_user_id=body.supervisor_user_id,
    )
    sup = str(body.supervisor_user_id) if body.supervisor_user_id else None
    await append_audit_record(
        db,
        AppendAuditRecordCommand(
            actor_id=admin.id,
            actor_role=admin.role_code,
            action="org.supervisor.set",
            summary=f"设置部门主管 {node.name}",
            target_type="sys_department",
            target_id=node.department_id,
            detail={"supervisor_user_id": sup},
        ),
    )
    return ok(_node(node))


@router.get("/nodes/{dept_id}/employees")
async def list_employees(dept_id: uuid.UUID, db: DB, _: CurrentUser) -> dict:
    """部门下的智能体员工。"""
    emps = await operations.list_department_employees(db, dept_id)
    return ok([_emp(e) for e in emps])


@router.post("/nodes/{dept_id}/employees")
async def create_employee(dept_id: uuid.UUID, body: EmployeeCreate, db: DB, _: Admin) -> dict:
    """在部门下新增智能体员工。"""
    role = await operations.create_department_expert(
        db,
        department_id=dept_id,
        name=body.name,
        prompt_template=body.prompt_template,
        duty=body.duty,
        model_role=body.model_role,
        tier=body.tier,
        title=body.title,
        report_to_id=body.report_to_id,
    )
    return ok(_emp(role))


@router.patch("/employees/{emp_id}")
async def update_employee(emp_id: uuid.UUID, body: EmployeeUpdate, db: DB, _: Admin) -> dict:
    """更新智能体员工。"""
    role = await operations.update_department_expert(
        db,
        expert_id=emp_id,
        name=body.name,
        prompt_template=body.prompt_template,
        duty=body.duty,
        model_role=body.model_role,
        is_active=body.is_active,
        title=body.title,
        tier=body.tier,
        report_to_id=body.report_to_id,
        department_id=body.department_id,
    )
    return ok(_emp(role))


@router.delete("/employees/{emp_id}")
async def delete_employee(emp_id: uuid.UUID, db: DB, _: Admin) -> dict:
    """删除智能体员工（骨架种子不可删）。"""
    await operations.delete_department_expert(db, emp_id)
    return ok()
