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
from app.models.agent import AgentRole, ExpertRelease


def _capabilities(tools: object) -> tuple[str, ...]:
    items = tools if isinstance(tools, list) else []
    return tuple(item for item in items if isinstance(item, str))


def _permissions(scope: object) -> tuple[tuple[str, str], ...]:
    mapping = scope if isinstance(scope, dict) else {}
    return tuple(
        (str(key), _permission_value(value))
        for key, value in sorted(mapping.items(), key=lambda item: str(item[0]))
    )


def snapshot_from_role(role: AgentRole) -> ExpertExecutionSnapshot:
    """Translate an ORM row into the published Expert snapshot."""
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
        capability_keys=_capabilities(role.tools),
        permission_entries=_permissions(role.permission_scope),
        owner_user_id=role.owner_user_id,
    )


def snapshot_from_release(role: AgentRole, release: ExpertRelease) -> ExpertExecutionSnapshot:
    """已发布快照驱动执行（Module 4 §4.4）：execution 字段取冻结 release，org 字段仍取活行。

    ADR 0008：release 只冻结 execution 子聚合；name/title/department/owner 属组织归属，不进不可变
    执行快照，故仍从 agent_role 读。version 取 v{version_no} 可复现该版。
    """
    return ExpertExecutionSnapshot(
        expert_id=role.id,
        version=f"v{release.version_no}",
        name=role.name,
        title=role.title or "",
        department_id=role.department_id,
        prompt_template=release.prompt_template,
        model_role=release.model_role,
        capability_keys=_capabilities(release.tools),
        permission_entries=_permissions(release.permission_scope),
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
        """已发布快照驱动执行（Module 4 §4.4）：有 current_release_id 读 release，否则回落活行。"""
        role = await self._find(AgentRole.id == expert_id)
        if role is None:
            return None
        if role.current_release_id is not None:
            release = await self._session.get(ExpertRelease, role.current_release_id)
            if release is not None:
                return snapshot_from_release(role, release)
        return snapshot_from_role(role)

    async def get_by_name(self, name: str) -> ExpertExecutionSnapshot | None:
        return self._snapshot(await self._find(AgentRole.name == name))

    async def get_by_code(self, code: str) -> ExpertExecutionSnapshot | None:
        return self._snapshot(await self._find(AgentRole.code == code))

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
