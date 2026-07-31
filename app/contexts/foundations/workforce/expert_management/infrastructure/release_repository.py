"""SQLAlchemy adapter for the immutable expert release面 (Module 2 / docs/23 §4.2)."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertReleaseView,
)
from app.contexts.foundations.workforce.expert_management.domain.models import ExpertRelease
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_repository import (  # noqa: E501
    _load_dict,
    _load_list,
)
from app.models.agent import AgentRole
from app.models.agent import ExpertRelease as ExpertReleaseRow


class SQLAlchemyExpertReleaseRepository:
    """只增快照行 + 推进 agent_role.current_release_id 软指针。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def next_version_no(self, expert_id: uuid.UUID) -> int:
        statement = select(func.coalesce(func.max(ExpertReleaseRow.version_no), 0)).where(
            ExpertReleaseRow.expert_id == expert_id
        )
        current = (await self._session.execute(statement)).scalar_one()
        return int(current) + 1

    async def add(self, release: ExpertRelease) -> None:
        self._session.add(
            ExpertReleaseRow(
                id=release.id,
                expert_id=release.expert_id,
                version_no=release.version_no,
                prompt_template=release.prompt_template,
                model_role=release.model_role,
                permission_scope=_load_dict(release.permission_scope_json),
                tools=_load_list(release.tools_json),
                duty=release.duty,
                released_by=release.released_by,
                eval_score=release.eval_score,
                eval_case_count=release.eval_case_count,
                create_time=release.released_at,
            )
        )

    async def set_current(self, expert_id: uuid.UUID, release_id: uuid.UUID) -> None:
        await self._session.execute(
            update(AgentRole)
            .where(AgentRole.id == expert_id)
            .values(current_release_id=release_id)
        )

    async def list_releases(self, expert_id: uuid.UUID) -> tuple[ExpertReleaseView, ...]:
        statement = (
            select(ExpertReleaseRow)
            .where(ExpertReleaseRow.expert_id == expert_id)
            .order_by(ExpertReleaseRow.version_no.desc())
        )
        rows = (await self._session.execute(statement)).scalars().all()
        return tuple(
            ExpertReleaseView(
                release_id=row.id,
                expert_id=row.expert_id,
                version_no=row.version_no,
                model_role=row.model_role,
                released_by=row.released_by,
                released_at=row.create_time,
                eval_score=row.eval_score,
                eval_case_count=row.eval_case_count,
            )
            for row in rows
        )
