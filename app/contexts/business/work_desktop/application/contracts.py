"""Plain request and result values for Work Desktop."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any


@dataclass(frozen=True, slots=True)
class DesktopPrincipal:
    id: uuid.UUID
    display_name: str
    role_code: str
    department_id: uuid.UUID | None = None
    is_deleted: bool = False

    @property
    def is_admin(self) -> bool:
        return self.role_code == "admin"

    @property
    def is_manager(self) -> bool:
        return self.role_code in {"admin", "executive"}


@dataclass(frozen=True, slots=True)
class TaskProjection:
    id: uuid.UUID
    title: str
    task_type: str
    status: str
    priority: str
    create_time: datetime


@dataclass(frozen=True, slots=True)
class ProposalProjection:
    id: uuid.UUID
    title: str
    code: str
    priority: str
    create_time: datetime


@dataclass(frozen=True, slots=True)
class ResolutionProjection:
    id: uuid.UUID
    content: str
    due_date: date | None
    create_time: datetime


@dataclass(frozen=True, slots=True)
class CollaborationProjection:
    id: uuid.UUID
    title: str
    risk_level: str
    create_time: datetime


@dataclass(frozen=True, slots=True)
class DeliverableProjection:
    id: uuid.UUID
    owner_user_id: uuid.UUID
    file_name: str
    file_format: str
    agent_name: str
    file_size: int
    storage_path: str
    create_time: datetime
    is_deleted: bool = False

    def as_dict(self) -> dict[str, str | int]:
        return {
            "id": str(self.id),
            "file_name": self.file_name,
            "file_format": self.file_format,
            "agent_name": self.agent_name,
            "file_size": self.file_size,
            "create_time": self.create_time.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class PendingItemResult:
    kind: str
    id: uuid.UUID
    title: str
    meta: str | None
    priority: str
    create_time: datetime
    score: float = 0.0
    is_read: bool = False
    is_processed: bool = False
    ai_summary: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "id": str(self.id),
            "title": self.title,
            "meta": self.meta,
            "priority": self.priority,
            "create_time": self.create_time.isoformat(),
            "score": self.score,
            "is_read": self.is_read,
            "is_processed": self.is_processed,
            "ai_summary": self.ai_summary,
        }


@dataclass(frozen=True, slots=True)
class InboxStateProjection:
    """某待办来源的读态（缺省=未读未处理无摘要）。"""

    is_read: bool = False
    is_processed: bool = False
    ai_summary: str | None = None


@dataclass(frozen=True, slots=True)
class InboxItemRef:
    """批量处理的目标条目引用（来源类型 + 源聚合 id）。"""

    kind: str
    id: uuid.UUID


@dataclass(frozen=True, slots=True)
class MyTaskResult:
    id: uuid.UUID
    title: str
    task_type: str
    status: str
    priority: str
    create_time: datetime

    def as_dict(self) -> dict[str, str]:
        return {
            "id": str(self.id),
            "title": self.title,
            "task_type": self.task_type,
            "status": self.status,
            "priority": self.priority,
            "create_time": self.create_time.isoformat(),
        }


@dataclass(frozen=True, slots=True)
class DesktopResult:
    principal: DesktopPrincipal
    pending: tuple[PendingItemResult, ...]
    my_tasks: tuple[MyTaskResult, ...]
    channel_count: int
    knowledge_count: int

    def as_dict(self) -> dict[str, Any]:
        pending = [item.as_dict() for item in self.pending]
        return {
            "user": {
                "id": str(self.principal.id),
                "name": self.principal.display_name,
                "role_code": self.principal.role_code,
            },
            "pending": pending,
            "pending_count": len(pending),
            "my_tasks": [task.as_dict() for task in self.my_tasks],
            "counts": {
                "channels": self.channel_count,
                "kbs": self.knowledge_count,
            },
        }


@dataclass(frozen=True, slots=True)
class DeliverableDownloadResult:
    file_name: str
    content: bytes
