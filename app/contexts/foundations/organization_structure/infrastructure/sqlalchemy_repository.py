"""SQLAlchemy mapper for Organization-owned department nodes."""

from __future__ import annotations

import uuid

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.organization_structure.domain.models import DepartmentNode
from app.models.system import SysDepartment


def _to_domain(row: SysDepartment) -> DepartmentNode:
    return DepartmentNode(
        id=row.id,
        version=(
            row.update_time.isoformat() if row.update_time is not None else f"unpersisted:{row.id}"
        ),
        name=row.name,
        code=row.code,
        node_type=row.node_type,
        level=row.level,
        path=row.path,
        parent_id=row.parent_id,
        supervisor_user_id=row.supervisor_user_id,
        sort_order=row.sort_order,
        create_time=row.create_time,
        is_deleted=row.is_delete,
        external_id=row.feishu_open_id,
    )


def _from_domain(node: DepartmentNode) -> SysDepartment:
    return SysDepartment(
        id=node.id,
        name=node.name,
        code=node.code,
        node_type=node.node_type,
        level=node.level,
        path=node.path,
        parent_id=node.parent_id,
        supervisor_user_id=node.supervisor_user_id,
        sort_order=node.sort_order,
        create_time=node.create_time,
        is_delete=node.is_deleted,
        feishu_open_id=node.external_id,
    )


class SQLAlchemyDepartmentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rows: dict[uuid.UUID, SysDepartment] = {}

    async def get(self, department_id: uuid.UUID) -> DepartmentNode | None:
        row = await self._session.get(SysDepartment, department_id)
        if row is None:
            return None
        # SQLAlchemy expires server-onupdate columns after UPDATE even when the
        # request session uses expire_on_commit=False. Refresh inside the async
        # adapter before the synchronous mapper reads those fields.
        await self._session.refresh(row)
        self._rows[department_id] = row
        return _to_domain(row)

    async def get_company_root(self) -> DepartmentNode | None:
        statement = select(SysDepartment).where(
            SysDepartment.node_type == "company",
            SysDepartment.is_delete.is_(False),
        )
        return await self._find(statement)

    async def get_by_code(self, code: str) -> DepartmentNode | None:
        statement = select(SysDepartment).where(
            SysDepartment.code == code,
            SysDepartment.is_delete.is_(False),
        )
        return await self._find(statement)

    async def get_by_parent_name(
        self, parent_id: uuid.UUID, name: str
    ) -> DepartmentNode | None:
        statement = select(SysDepartment).where(
            SysDepartment.parent_id == parent_id,
            SysDepartment.name == name,
            SysDepartment.is_delete.is_(False),
        )
        return await self._find(statement)

    async def get_by_external_id(self, external_id: str) -> DepartmentNode | None:
        statement = select(SysDepartment).where(
            SysDepartment.feishu_open_id == external_id,
            SysDepartment.is_delete.is_(False),
        )
        return await self._find(statement)

    async def _find(
        self, statement: Select[tuple[SysDepartment]]
    ) -> DepartmentNode | None:
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        self._rows[row.id] = row
        return _to_domain(row)

    async def list_nodes(self) -> list[DepartmentNode]:
        statement = (
            select(SysDepartment)
            .where(SysDepartment.is_delete.is_(False))
            .order_by(
                SysDepartment.level,
                SysDepartment.sort_order,
                SysDepartment.create_time,
            )
            .execution_options(populate_existing=True)
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return [_to_domain(row) for row in rows]

    async def has_active_child(self, department_id: uuid.UUID) -> bool:
        statement = select(SysDepartment.id).where(
            SysDepartment.parent_id == department_id,
            SysDepartment.is_delete.is_(False),
        )
        return (await self._session.execute(statement)).first() is not None

    async def add(self, department: DepartmentNode) -> None:
        row = _from_domain(department)
        self._rows[department.id] = row
        self._session.add(row)

    async def save(self, department: DepartmentNode) -> None:
        row = self._rows.get(department.id)
        if row is None:
            row = await self._session.get(SysDepartment, department.id)
        if row is None:
            return
        row.name = department.name
        row.code = department.code
        row.node_type = department.node_type
        row.level = department.level
        row.path = department.path
        row.parent_id = department.parent_id
        row.supervisor_user_id = department.supervisor_user_id
        row.sort_order = department.sort_order
        row.is_delete = department.is_deleted
        row.feishu_open_id = department.external_id
