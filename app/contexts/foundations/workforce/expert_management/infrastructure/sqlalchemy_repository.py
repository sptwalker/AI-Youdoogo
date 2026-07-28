"""SQLAlchemy mapper for Expert Management-owned profiles."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.contexts.foundations.workforce.expert_management.domain.models import (
    ExpertExecutionDefinition,
    ExpertProfile,
    OrgExpertMember,
)
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
    # ponytail: 单表 agent_role 一行重建两子聚合；物理拆表待 docs/21 Phase 3
    return ExpertProfile(
        id=row.id,
        version=(
            row.update_time.isoformat() if row.update_time is not None else f"unpersisted:{row.id}"
        ),
        create_time=row.create_time,
        member=OrgExpertMember(
            code=row.code,
            name=row.name,
            title=row.title or "",
            tier=row.tier,
            department_id=row.department_id,
            report_to_id=row.report_to_id,
            owner_user_id=row.owner_user_id,
            is_seed=row.is_seed,
            is_active=row.is_active,
            is_deleted=row.is_delete,
        ),
        execution=ExpertExecutionDefinition(
            prompt_template=row.prompt_template,
            model_role=row.model_role,
            permission_scope_json=_dump(row.permission_scope or {}),
            tools_json=_dump(row.tools or []),
            duty=row.duty,
        ),
    )


def _from_domain(expert: ExpertProfile) -> AgentRole:
    member, execution = expert.member, expert.execution
    return AgentRole(
        id=expert.id,
        code=member.code,
        name=member.name,
        title=member.title,
        tier=member.tier,
        department_id=member.department_id,
        report_to_id=member.report_to_id,
        owner_user_id=member.owner_user_id,
        duty=execution.duty,
        prompt_template=execution.prompt_template,
        model_role=execution.model_role,
        permission_scope=_load_dict(execution.permission_scope_json),
        tools=_load_list(execution.tools_json),
        is_seed=member.is_seed,
        is_active=member.is_active,
        create_time=expert.create_time,
        is_delete=member.is_deleted,
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
        member, execution = expert.member, expert.execution
        row.code = member.code
        row.name = member.name
        row.title = member.title
        row.tier = member.tier
        row.department_id = member.department_id
        row.report_to_id = member.report_to_id
        row.owner_user_id = member.owner_user_id
        row.duty = execution.duty
        row.prompt_template = execution.prompt_template
        row.model_role = execution.model_role
        row.permission_scope = _load_dict(execution.permission_scope_json)
        row.tools = _load_list(execution.tools_json)
        row.is_seed = member.is_seed
        row.is_active = member.is_active
        row.is_delete = member.is_deleted
