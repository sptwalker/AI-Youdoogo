"""SQLAlchemy mapper for Expert Management-owned profiles."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.contexts.foundations.workforce.expert_management.domain.models import ExpertProfile
from app.models.agent import AgentRole


def _dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_dict(value: str) -> dict[str, Any]:
    loaded = json.loads(value)
    return loaded if isinstance(loaded, dict) else {}


def _load_list(value: str) -> list[Any]:
    loaded = json.loads(value)
    return loaded if isinstance(loaded, list) else []


def _to_domain(row: AgentRole) -> ExpertProfile:
    return ExpertProfile(
        id=row.id,
        version=(
            row.update_time.isoformat() if row.update_time is not None else f"unpersisted:{row.id}"
        ),
        code=row.code,
        name=row.name,
        title=row.title or "",
        tier=row.tier,
        department_id=row.department_id,
        report_to_id=row.report_to_id,
        owner_user_id=row.owner_user_id,
        duty=row.duty,
        prompt_template=row.prompt_template,
        model_role=row.model_role,
        permission_scope_json=_dump(row.permission_scope or {}),
        tools_json=_dump(row.tools or []),
        is_seed=row.is_seed,
        is_active=row.is_active,
        create_time=row.create_time,
        is_deleted=row.is_delete,
    )


def _from_domain(expert: ExpertProfile) -> AgentRole:
    return AgentRole(
        id=expert.id,
        code=expert.code,
        name=expert.name,
        title=expert.title,
        tier=expert.tier,
        department_id=expert.department_id,
        report_to_id=expert.report_to_id,
        owner_user_id=expert.owner_user_id,
        duty=expert.duty,
        prompt_template=expert.prompt_template,
        model_role=expert.model_role,
        permission_scope=_load_dict(expert.permission_scope_json),
        tools=_load_list(expert.tools_json),
        is_seed=expert.is_seed,
        is_active=expert.is_active,
        create_time=expert.create_time,
        is_delete=expert.is_deleted,
    )


class SQLAlchemyExpertRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._rows: dict[uuid.UUID, AgentRole] = {}

    async def get(self, expert_id: uuid.UUID) -> ExpertProfile | None:
        row = await self._session.get(AgentRole, expert_id)
        if row is None:
            return None
        self._rows[expert_id] = row
        return _to_domain(row)

    async def get_by_code(self, code: str) -> ExpertProfile | None:
        return await self._find(AgentRole.code == code)

    async def get_by_name(self, name: str) -> ExpertProfile | None:
        return await self._find(AgentRole.name == name)

    async def _find(self, criterion: ColumnElement[bool]) -> ExpertProfile | None:
        statement = select(AgentRole).where(
            criterion,
            AgentRole.is_delete.is_(False),
        )
        row = (await self._session.execute(statement)).scalar_one_or_none()
        if row is None:
            return None
        self._rows[row.id] = row
        return _to_domain(row)

    async def add(self, expert: ExpertProfile) -> None:
        row = _from_domain(expert)
        self._rows[expert.id] = row
        self._session.add(row)

    async def save(self, expert: ExpertProfile) -> None:
        row = self._rows.get(expert.id)
        if row is None:
            row = await self._session.get(AgentRole, expert.id)
        if row is None:
            return
        row.code = expert.code
        row.name = expert.name
        row.title = expert.title
        row.tier = expert.tier
        row.department_id = expert.department_id
        row.report_to_id = expert.report_to_id
        row.owner_user_id = expert.owner_user_id
        row.duty = expert.duty
        row.prompt_template = expert.prompt_template
        row.model_role = expert.model_role
        row.permission_scope = _load_dict(expert.permission_scope_json)
        row.tools = _load_list(expert.tools_json)
        row.is_seed = expert.is_seed
        row.is_active = expert.is_active
        row.is_delete = expert.is_deleted
