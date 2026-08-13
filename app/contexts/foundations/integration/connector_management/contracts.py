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


@dataclass(frozen=True, slots=True)
class ConnectorProbeResult:
    """连通测试结果，前端读 status/message/row_count。

    status: ok / fail / not_configured / unsupported。
    """

    status: str
    message: str
    row_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {"status": self.status, "message": self.message, "row_count": self.row_count}


@dataclass(frozen=True, slots=True)
class HttpFetchResult:
    """http_api 只读取数结果（对称补全 ConnectorProbeResult，探针只连通、本结果带 body）。

    status: ok / fail / not_configured。records 为归一后的结构化记录（JSON 列表/对象→dict 列表），
    text 为原始文本预览（非 JSON 或作为兜底，已截断上限），供下游按需取用。外部正文进 agent
    _interpret 前须由调用方防注入 fence 包裹（本层只取数、不喂 LLM）。
    """

    status: str
    message: str
    records: tuple[dict[str, Any], ...] = ()
    text: str = ""

    @property
    def row_count(self) -> int:
        return len(self.records)
