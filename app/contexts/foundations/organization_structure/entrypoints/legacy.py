"""Legacy Organization response mappers."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.contexts.foundations.organization_structure.contracts import (
    DepartmentSnapshot,
    OrganizationSnapshot,
    OrganizationTreeNodeSnapshot,
)


@dataclass(frozen=True, slots=True)
class LegacyDepartmentView:
    id: uuid.UUID
    name: str
    code: str
    node_type: str
    level: int
    path: str
    parent_id: uuid.UUID | None
    supervisor_user_id: uuid.UUID | None
    sort_order: int
    create_time: datetime


def department_view(snapshot: DepartmentSnapshot) -> LegacyDepartmentView:
    return LegacyDepartmentView(
        id=snapshot.department_id,
        name=snapshot.name,
        code=snapshot.code,
        node_type=snapshot.node_type,
        level=snapshot.level,
        path=snapshot.path,
        parent_id=snapshot.parent_id,
        supervisor_user_id=snapshot.supervisor_user_id,
        sort_order=snapshot.sort_order,
        create_time=snapshot.create_time,
    )


def _tree_node(snapshot: OrganizationTreeNodeSnapshot) -> dict[str, Any]:
    department = snapshot.department
    return {
        "id": str(department.department_id),
        "name": department.name,
        "code": department.code,
        "node_type": department.node_type,
        "level": department.level,
        "parent_id": str(department.parent_id) if department.parent_id else None,
        "supervisor_user_id": (
            str(department.supervisor_user_id) if department.supervisor_user_id else None
        ),
        "employee_count": snapshot.employee_count,
        "children": [_tree_node(child) for child in snapshot.children],
    }


def tree_view(snapshot: OrganizationSnapshot) -> list[dict[str, Any]]:
    return [_tree_node(root) for root in snapshot.roots]
