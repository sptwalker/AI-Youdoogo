"""Published immutable Organization Structure snapshots."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class DepartmentSnapshot:
    department_id: uuid.UUID
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


@dataclass(frozen=True, slots=True)
class OrganizationTreeNodeSnapshot:
    department: DepartmentSnapshot
    employee_count: int
    children: tuple[OrganizationTreeNodeSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class OrganizationSnapshot:
    version: str
    roots: tuple[OrganizationTreeNodeSnapshot, ...]
