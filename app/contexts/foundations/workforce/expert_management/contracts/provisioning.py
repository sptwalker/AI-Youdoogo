"""Cross-Context Expert provisioning port (session-free write signature).

Phase 1（docs/21 §11）由 RemoteExpertProvisioningAdapter 实现同一签名，
届时仅换 ``public.build_local_expert_provisioning_port`` 的返回实现即可全量改道。
``permission_scope``/``tools`` 仍收 dict/list，序列化在适配器内完成（与既有会话级写函数对齐）。
"""

from __future__ import annotations

import uuid
from typing import Protocol

from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    ExpertRosterSnapshot,
)


class ExpertProvisioningPort(Protocol):
    """会话无关的专家写侧端口——跨 Context 写消费方一律经此落库。"""

    async def create(
        self,
        *,
        name: str,
        prompt_template: str,
        duty: str | None,
        model_role: str,
        department_id: uuid.UUID | None,
        permission_scope: dict[str, object],
        tools: list[object],
        tier: str,
        title: str,
        report_to_id: uuid.UUID | None,
        owner_user_id: uuid.UUID | None = None,
    ) -> ExpertRosterSnapshot: ...

    async def update(
        self,
        *,
        expert_id: uuid.UUID,
        name: str | None,
        prompt_template: str | None,
        duty: str | None,
        model_role: str | None,
        is_active: bool | None,
        permission_scope: dict[str, object] | None,
        tools: list[object] | None,
        title: str | None,
        tier: str | None,
        report_to_id: uuid.UUID | None,
        department_id: uuid.UUID | None,
    ) -> ExpertRosterSnapshot: ...

    async def delete(self, expert_id: uuid.UUID) -> None: ...

    async def seed(
        self,
        *,
        code: str,
        name: str,
        prompt_template: str,
        title: str,
        tier: str,
        model_role: str,
        department_id: uuid.UUID | None,
        duty: str | None = None,
        report_to_id: uuid.UUID | None = None,
    ) -> ExpertRosterSnapshot: ...
