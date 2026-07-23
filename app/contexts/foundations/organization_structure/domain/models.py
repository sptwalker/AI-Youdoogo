"""Organization hierarchy rules without ORM dependencies."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.contexts.shared_kernel import RuleViolation

COMPANY = "company"
DEPT_L1 = "dept_l1"
DEPT_L2 = "dept_l2"
NODE_TYPE_BY_LEVEL = {0: COMPANY, 1: DEPT_L1, 2: DEPT_L2}


@dataclass(slots=True)
class DepartmentNode:
    id: uuid.UUID
    version: str
    name: str
    code: str
    node_type: str
    level: int
    path: str
    parent_id: uuid.UUID | None
    supervisor_user_id: uuid.UUID | None
    sort_order: int
    create_time: datetime
    is_deleted: bool = False
    external_id: str | None = None

    @classmethod
    def create_company(
        cls,
        *,
        company_id: uuid.UUID,
        name: str,
        code: str,
        supervisor_user_id: uuid.UUID | None,
        create_time: datetime,
    ) -> DepartmentNode:
        return cls(
            id=company_id,
            version="new",
            name=name,
            code=code,
            node_type=COMPANY,
            level=0,
            path=f"/{company_id}/",
            parent_id=None,
            supervisor_user_id=supervisor_user_id,
            sort_order=0,
            create_time=create_time,
        )

    def create_child(
        self,
        *,
        child_id: uuid.UUID,
        name: str,
        code: str,
        create_time: datetime,
    ) -> DepartmentNode:
        level = self.level + 1
        if level > 2:
            raise RuleViolation("部门层级最多两级（一级/二级），不能再往下建")
        return DepartmentNode(
            id=child_id,
            version="new",
            name=name,
            code=code,
            node_type=NODE_TYPE_BY_LEVEL[level],
            level=level,
            path=f"{self.path}{child_id}/",
            parent_id=self.id,
            supervisor_user_id=None,
            sort_order=0,
            create_time=create_time,
        )

    def update(self, *, name: str | None, sort_order: int | None) -> None:
        if self.node_type == COMPANY and name is not None:
            raise RuleViolation("公司根节点名称不可改（如需改公司名走系统配置）")
        if name is not None:
            self.name = name
        if sort_order is not None:
            self.sort_order = sort_order

    def normalize_template_child(
        self,
        *,
        root: DepartmentNode,
        code: str,
        name: str,
        sort_order: int,
    ) -> None:
        self.code = code
        self.name = name
        self.parent_id = root.id
        self.node_type = DEPT_L1
        self.level = 1
        self.sort_order = sort_order
        self.path = f"{root.path}{self.id}/"

    def set_supervisor(self, supervisor_user_id: uuid.UUID | None) -> None:
        self.supervisor_user_id = supervisor_user_id

    def create_external_child(
        self,
        *,
        child_id: uuid.UUID,
        external_id: str,
        name: str,
        create_time: datetime,
    ) -> DepartmentNode:
        return DepartmentNode(
            id=child_id,
            version="new",
            name=name,
            code=f"fs_{external_id[:24]}",
            node_type=DEPT_L1,
            level=self.level + 1,
            path=f"{self.path}{child_id}/",
            parent_id=self.id,
            supervisor_user_id=None,
            sort_order=0,
            create_time=create_time,
            external_id=external_id,
        )

    def move_external_child(self, *, parent: DepartmentNode, name: str) -> None:
        self.name = name
        self.parent_id = parent.id
        self.level = parent.level + 1
        self.path = f"{parent.path}{self.id}/"

    def ancestor_ids(self) -> tuple[uuid.UUID, ...]:
        return tuple(
            uuid.UUID(segment)
            for segment in self.path.strip("/").split("/")
            if segment
        )

    def delete(self) -> None:
        if self.node_type == COMPANY:
            raise RuleViolation("公司根节点不可删除")
        self.is_deleted = True
