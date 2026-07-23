"""Published Connector Management language."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ConnectorSnapshot:
    id: uuid.UUID
    name: str
    code: str
    connector_type: str
    department_id: uuid.UUID | None
    config: dict[str, object]
    secret_ref: str | None
    secret_status: str
    is_active: bool
    owner_expert_id: uuid.UUID | None
    owner_expert_name: str | None

    @property
    def type(self) -> str:
        """Legacy attribute retained while callers migrate to connector_type."""
        return self.connector_type

    @property
    def owner_agent_id(self) -> uuid.UUID | None:
        """Legacy vocabulary retained at the compatibility boundary."""
        return self.owner_expert_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "name": self.name,
            "code": self.code,
            "type": self.connector_type,
            "department_id": str(self.department_id) if self.department_id else None,
            "config": self.config,
            "secret_ref": self.secret_ref,
            "secret_status": self.secret_status,
            "is_active": self.is_active,
            "owner_agent_id": str(self.owner_expert_id) if self.owner_expert_id else None,
            "owner_agent_name": self.owner_expert_name,
        }
