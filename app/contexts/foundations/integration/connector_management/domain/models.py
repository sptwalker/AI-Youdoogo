"""Framework-independent Connector model."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.contexts.shared_kernel import RuleViolation

VALID_CONNECTOR_TYPES = (
    "thinkingdata",
    "feishu_bitable",
    "feishu_docx",
    "excel",
    "http_api",
)


@dataclass(slots=True)
class Connector:
    id: uuid.UUID
    name: str
    code: str
    connector_type: str
    department_id: uuid.UUID | None = None
    config: dict[str, object] = field(default_factory=dict)
    secret_ref: str | None = None
    is_active: bool = True
    owner_expert_id: uuid.UUID | None = None

    def validate(self) -> None:
        if not self.name.strip():
            raise RuleViolation("数据接口名称必填")
        if self.connector_type not in VALID_CONNECTOR_TYPES:
            raise RuleViolation(f"type 仅支持 {'/'.join(VALID_CONNECTOR_TYPES)}")
