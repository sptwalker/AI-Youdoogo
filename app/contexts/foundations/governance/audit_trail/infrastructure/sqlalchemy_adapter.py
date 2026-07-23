"""SQLAlchemy persistence for append-only audit evidence."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.governance.audit_trail.application.ports import (
    AuditRecordRepositoryPort,
    AuditUnitOfWork,
)
from app.contexts.foundations.governance.audit_trail.application.use_cases import (
    AppendAuditRecord,
    QueryAuditTrail,
)
from app.contexts.foundations.governance.audit_trail.contracts.audit import (
    AppendAuditRecordCommand,
    AuditRecordView,
    AuditTrailQuery,
)
from app.models.audit_log import AuditLog


class SQLAlchemyAuditRecordRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, command: AppendAuditRecordCommand) -> None:
        self._session.add(
            AuditLog(
                actor_id=command.actor_id,
                actor_role=command.actor_role,
                action=command.action,
                target_type=command.target_type,
                target_id=command.target_id,
                summary=command.summary,
                detail=dict(command.detail) if command.detail is not None else None,
                result=command.result,
            )
        )

    async def list(self, query: AuditTrailQuery) -> tuple[AuditRecordView, ...]:
        statement = select(AuditLog)
        if query.action:
            statement = statement.where(AuditLog.action == query.action)
        if query.actor_id:
            statement = statement.where(AuditLog.actor_id == query.actor_id)
        statement = statement.order_by(AuditLog.create_time.desc()).limit(query.limit)
        rows = (await self._session.execute(statement)).scalars()
        return tuple(
            AuditRecordView(
                record_id=row.id,
                actor_id=row.actor_id,
                actor_role=row.actor_role,
                action=row.action,
                target_type=row.target_type,
                target_id=row.target_id,
                summary=row.summary,
                detail=row.detail,
                result=row.result,
                occurred_at=row.create_time.isoformat(),
            )
            for row in rows
        )


class SQLAlchemyAuditUnitOfWork:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self.records: AuditRecordRepositoryPort = SQLAlchemyAuditRecordRepository(session)

    async def commit(self) -> None:
        await self._session.commit()

    async def rollback(self) -> None:
        await self._session.rollback()


class SQLAlchemyAuditUnitOfWorkFactory:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    def __call__(self) -> AuditUnitOfWork:
        return SQLAlchemyAuditUnitOfWork(self._session)


class LoggingAuditFailureReporter:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def record_failure(self, action: str, actor_id: object) -> None:
        self._logger.error(
            "写审计最终失败 action=%s actor=%s",
            action,
            actor_id,
            exc_info=True,
        )


class SQLAlchemyAuditTrail:
    def __init__(self, session: AsyncSession, *, logger: logging.Logger) -> None:
        units = SQLAlchemyAuditUnitOfWorkFactory(session)
        self._append = AppendAuditRecord(units, LoggingAuditFailureReporter(logger))
        self._query = QueryAuditTrail(units)

    async def append(self, command: AppendAuditRecordCommand) -> None:
        await self._append.execute(command)

    async def query(self, query: AuditTrailQuery) -> tuple[AuditRecordView, ...]:
        return await self._query.execute(query)
