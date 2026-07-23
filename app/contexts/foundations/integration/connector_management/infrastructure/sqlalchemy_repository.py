"""SQLAlchemy mapper and repository for the existing data_source table."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contexts.foundations.integration.connector_management.domain.models import Connector
from app.contexts.shared_kernel import ConflictDetected
from app.models.knowledge import DataSource


def connector_to_domain(row: DataSource) -> Connector:
    return Connector(
        id=row.id,
        name=row.name,
        code=row.code,
        connector_type=row.type,
        department_id=row.department_id,
        config=dict(row.config or {}),
        secret_ref=row.secret_ref,
        is_active=row.is_active,
        owner_expert_id=row.owner_agent_id,
    )


class SQLAlchemyConnectorRepository:
    """Persist Connector state using flush-only repository methods."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._tracked: dict[uuid.UUID, DataSource] = {}

    async def get(self, connector_id: uuid.UUID) -> Connector | None:
        row = await self._session.get(DataSource, connector_id)
        if row is None or row.is_delete:
            return None
        self._tracked[row.id] = row
        return connector_to_domain(row)

    async def code_exists(self, code: str) -> bool:
        statement = select(DataSource.id).where(
            DataSource.code == code,
            DataSource.is_delete.is_(False),
        )
        return (await self._session.execute(statement)).scalar_one_or_none() is not None

    async def list_records(self) -> tuple[Connector, ...]:
        statement = (
            select(DataSource)
            .where(DataSource.is_delete.is_(False))
            .order_by(DataSource.create_time)
        )
        rows = tuple((await self._session.execute(statement)).scalars())
        self._tracked.update({row.id: row for row in rows})
        return tuple(connector_to_domain(row) for row in rows)

    async def add(self, connector: Connector) -> None:
        row = DataSource(
            id=connector.id,
            name=connector.name,
            code=connector.code,
            type=connector.connector_type,
            department_id=connector.department_id,
            config=dict(connector.config),
            secret_ref=connector.secret_ref,
            is_active=connector.is_active,
            owner_agent_id=connector.owner_expert_id,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ConflictDetected("数据接口编码已存在") from exc
        self._tracked[connector.id] = row

    async def save(self, connector: Connector) -> None:
        row = self._tracked.get(connector.id)
        if row is None:
            row = await self._session.get(DataSource, connector.id)
        if row is None or row.is_delete:
            return
        row.name = connector.name
        row.code = connector.code
        row.type = connector.connector_type
        row.department_id = connector.department_id
        row.config = dict(connector.config)
        row.secret_ref = connector.secret_ref
        row.is_active = connector.is_active
        row.owner_agent_id = connector.owner_expert_id
        await self._session.flush()
        self._tracked[connector.id] = row

    async def soft_delete(self, connector_id: uuid.UUID) -> None:
        row = self._tracked.get(connector_id)
        if row is None:
            row = await self._session.get(DataSource, connector_id)
        if row is None or row.is_delete:
            return
        row.is_delete = True
        await self._session.flush()
