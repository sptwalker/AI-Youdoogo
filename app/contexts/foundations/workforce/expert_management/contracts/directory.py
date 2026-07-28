"""Cross-Context read-only Expert directory port (session-free signature).

Phase 1（docs/21 §11）由 RemoteExpertDirectoryAdapter 实现同一签名，
届时仅换 ``public.build_local_expert_directory_port`` 的返回实现即可全量改道。
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)


class ExpertDirectoryPort(Protocol):
    """会话无关的专家目录只读端口——跨 Context 消费方一律经此拿数据。"""

    async def get_execution(
        self, expert_id: uuid.UUID
    ) -> ExpertExecutionSnapshot | None: ...

    async def get_roster(
        self, expert_id: uuid.UUID
    ) -> ExpertRosterSnapshot | None: ...

    async def list_roster(
        self, *, include_personal: bool = True
    ) -> tuple[ExpertRosterSnapshot, ...]: ...

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]: ...

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]: ...
