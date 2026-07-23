"""Legacy attribute view built from the published Expert roster snapshot."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    ExpertRosterSnapshot,
)


@dataclass(frozen=True, slots=True)
class LegacyExpertView:
    id: uuid.UUID
    code: str | None
    name: str
    title: str
    tier: str
    department_id: uuid.UUID | None
    report_to_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    duty: str | None
    prompt_template: str
    model_role: str
    permission_scope: dict[str, Any]
    tools: list[Any]
    is_seed: bool
    is_active: bool
    create_time: datetime
    update_time: datetime | None
    is_delete: bool = False


def legacy_view(snapshot: ExpertRosterSnapshot) -> LegacyExpertView:
    permission_scope = json.loads(snapshot.permission_scope_json)
    tools = json.loads(snapshot.tools_json)
    update_time = (
        datetime.fromisoformat(snapshot.version)
        if not snapshot.version.startswith(("new", "unpersisted:"))
        else None
    )
    return LegacyExpertView(
        id=snapshot.expert_id,
        code=snapshot.code,
        name=snapshot.name,
        title=snapshot.title,
        tier=snapshot.tier,
        department_id=snapshot.department_id,
        report_to_id=snapshot.report_to_id,
        owner_user_id=snapshot.owner_user_id,
        duty=snapshot.duty,
        prompt_template=snapshot.prompt_template,
        model_role=snapshot.model_role,
        permission_scope=permission_scope if isinstance(permission_scope, dict) else {},
        tools=tools if isinstance(tools, list) else [],
        is_seed=snapshot.is_seed,
        is_active=snapshot.is_active,
        create_time=snapshot.create_time,
        update_time=update_time,
    )
