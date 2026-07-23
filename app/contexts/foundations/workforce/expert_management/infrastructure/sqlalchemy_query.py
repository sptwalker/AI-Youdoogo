"""SQLAlchemy adapter for immutable expert execution snapshots."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.models.agent import AgentRole


def snapshot_from_role(role: AgentRole) -> ExpertExecutionSnapshot:
    """Translate an ORM row into the published Expert snapshot."""
    capabilities = tuple(item for item in (role.tools or []) if isinstance(item, str))
    permissions = tuple(
        (str(key), _permission_value(value))
        for key, value in sorted(
            (role.permission_scope or {}).items(), key=lambda item: str(item[0])
        )
    )
    return ExpertExecutionSnapshot(
        expert_id=role.id,
        version=(
            role.update_time.isoformat()
            if role.update_time is not None
            else f"unpersisted:{role.id}"
        ),
        name=role.name,
        title=role.title or "",
        department_id=role.department_id,
        prompt_template=role.prompt_template,
        model_role=role.model_role,
        capability_keys=capabilities,
        permission_entries=permissions,
        owner_user_id=role.owner_user_id,
    )


def _permission_value(value: object) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def roster_snapshot_from_role(role: AgentRole) -> ExpertRosterSnapshot:
    """Translate a roster row into a lossless immutable JSON snapshot."""
    return ExpertRosterSnapshot(
        expert_id=role.id,
        version=(
            role.update_time.isoformat()
            if role.update_time is not None
            else f"unpersisted:{role.id}"
        ),
        code=role.code,
        name=role.name,
        title=role.title or "",
        tier=role.tier,
        department_id=role.department_id,
        report_to_id=role.report_to_id,
        owner_user_id=role.owner_user_id,
        duty=role.duty,
        prompt_template=role.prompt_template,
        model_role=role.model_role,
        permission_scope_json=json.dumps(
            role.permission_scope or {},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        tools_json=json.dumps(
            role.tools or [],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        is_seed=role.is_seed,
        is_active=role.is_active,
        create_time=role.create_time,
    )


class SQLAlchemyExpertSnapshotQuery:
    """Load only active, non-deleted experts and publish snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, expert_id: uuid.UUID) -> ExpertExecutionSnapshot | None:
        return self._snapshot(await self._find(AgentRole.id == expert_id))

    async def get_by_name(self, name: str) -> ExpertExecutionSnapshot | None:
        return self._snapshot(await self._find(AgentRole.name == name))

    async def get_by_code(self, code: str) -> ExpertExecutionSnapshot | None:
        return self._snapshot(await self._find(AgentRole.code == code))

    async def get_record_by_id(self, expert_id: uuid.UUID) -> AgentRole | None:
        """Compatibility seam for callers that still require the mapped row."""
        return await self._find(AgentRole.id == expert_id)

    async def get_record_by_name(self, name: str) -> AgentRole | None:
        """Compatibility seam for the legacy Agent facade."""
        return await self._find(AgentRole.name == name)

    async def get_record_by_code(self, code: str) -> AgentRole | None:
        """Compatibility seam for the legacy Agent facade."""
        return await self._find(AgentRole.code == code)

    async def _find(self, criterion: ColumnElement[bool]) -> AgentRole | None:
        statement = select(AgentRole).where(
            criterion,
            AgentRole.is_active.is_(True),
            AgentRole.is_delete.is_(False),
        )
        return (await self._session.execute(statement)).scalar_one_or_none()

    @staticmethod
    def _snapshot(role: AgentRole | None) -> ExpertExecutionSnapshot | None:
        return snapshot_from_role(role) if role is not None else None


class SQLAlchemyExpertRosterQuery:
    """Read stable roster snapshots from the existing AgentRole table."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_roster_by_id(self, expert_id: uuid.UUID) -> ExpertRosterSnapshot | None:
        statement = select(AgentRole).where(
            AgentRole.id == expert_id,
            AgentRole.is_delete.is_(False),
        ).execution_options(populate_existing=True)
        role = (await self._session.execute(statement)).scalar_one_or_none()
        return roster_snapshot_from_role(role) if role is not None else None

    async def list_roster(
        self, *, include_personal: bool = False
    ) -> tuple[ExpertRosterSnapshot, ...]:
        statement = select(AgentRole).where(AgentRole.is_delete.is_(False))
        if not include_personal:
            statement = statement.where(AgentRole.owner_user_id.is_(None))
        statement = statement.order_by(AgentRole.create_time).execution_options(
            populate_existing=True
        )
        roles = (await self._session.execute(statement)).scalars().all()
        return tuple(roster_snapshot_from_role(role) for role in roles)

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]:
        statement = (
            select(AgentRole)
            .where(
                AgentRole.department_id == department_id,
                AgentRole.is_delete.is_(False),
                AgentRole.owner_user_id.is_(None),
            )
            .order_by(AgentRole.tier, AgentRole.create_time)
            .execution_options(populate_existing=True)
        )
        roles = (await self._session.execute(statement)).scalars().all()
        return tuple(roster_snapshot_from_role(role) for role in roles)

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]:
        statement = (
            select(AgentRole.department_id, func.count())
            .where(
                AgentRole.is_delete.is_(False),
                AgentRole.department_id.is_not(None),
            )
            .group_by(AgentRole.department_id)
        )
        if not include_personal:
            statement = statement.where(AgentRole.owner_user_id.is_(None))
        rows = (await self._session.execute(statement)).all()
        return tuple(
            DepartmentExpertCount(department_id=department_id, count=int(count))
            for department_id, count in rows
            if department_id is not None
        )
