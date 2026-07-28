"""In-process Expert directory adapter — satisfies ExpertDirectoryPort.

Phase 1 的 RemoteExpertDirectoryAdapter 将实现同一 ExpertDirectoryPort；
消费方经 public.build_local_expert_directory_port 拿端口，绝不直连本文件。
"""

from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.workforce.expert_management.contracts.directory import (
    ExpertDirectoryPort,
)
from app.contexts.foundations.workforce.expert_management.contracts.execution import (
    ExpertExecutionSnapshot,
)
from app.contexts.foundations.workforce.expert_management.contracts.roster import (
    DepartmentExpertCount,
    ExpertRosterSnapshot,
)
from app.contexts.foundations.workforce.expert_management.infrastructure.sqlalchemy_query import (
    SQLAlchemyExpertRosterQuery,
    SQLAlchemyExpertSnapshotQuery,
)


class LocalExpertDirectoryAdapter:
    """会话绑定的本地专家目录端口——满足 ExpertDirectoryPort。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_execution(
        self, expert_id: uuid.UUID
    ) -> ExpertExecutionSnapshot | None:
        return await SQLAlchemyExpertSnapshotQuery(self._session).get_by_id(expert_id)

    async def get_roster(
        self, expert_id: uuid.UUID
    ) -> ExpertRosterSnapshot | None:
        return await SQLAlchemyExpertRosterQuery(self._session).get_roster_by_id(expert_id)

    async def list_roster(
        self, *, include_personal: bool = True
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return await SQLAlchemyExpertRosterQuery(self._session).list_roster(
            include_personal=include_personal
        )

    async def list_department_roster(
        self, department_id: uuid.UUID
    ) -> tuple[ExpertRosterSnapshot, ...]:
        return await SQLAlchemyExpertRosterQuery(self._session).list_department_roster(
            department_id
        )

    async def count_by_department(
        self, *, include_personal: bool
    ) -> tuple[DepartmentExpertCount, ...]:
        return await SQLAlchemyExpertRosterQuery(self._session).count_by_department(
            include_personal=include_personal
        )


def _assert_protocol() -> None:
    # ponytail: 编译期协议符合性检查，运行时不执行
    _: ExpertDirectoryPort = LocalExpertDirectoryAdapter.__new__(LocalExpertDirectoryAdapter)
